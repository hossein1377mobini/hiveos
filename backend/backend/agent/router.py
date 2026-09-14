"""User-facing agent endpoints (PO 2026-09): my agent, my memory, my tools.

Everything here is scoped to the *authenticated user inside their organization*.
There is deliberately no "get agent by id" route: a per-user agent is reachable
only as "mine", so a guessed uuid cannot read someone else's memory. The
organization_id and user_id always come from the auth context, never the path.

What the user can do:

  GET    /agent                  - my agent: persona, status, tool allowlist
  PATCH  /agent                  - change my persona / display name
  GET    /agent/memory           - what my agent remembers (paged, filterable)
  POST   /agent/memory           - teach it something explicitly
  DELETE /agent/memory/{id}      - forget one memory
  GET    /agent/tools            - tools my agent has, and which are enabled
  PATCH  /agent/tools            - set my tool allowlist
  GET    /agent/activity         - my recent tool calls (the trace)

The activity route is the user's window into the same trace the admin panel
reads: the PO asked that every action be traceable, and the person best placed
to notice a wrong action is the one who asked for it.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent import memory as agent_memory
from backend.agent.service import agent_payload, update_agent_settings
from backend.agent.tools import registry as tool_registry
from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.models import AgentMemory, AgentToolInvocation
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/agent")

_agent_limiter = SlidingWindowLimiter(max_events=90, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_agent_limiter)

MEMORY_PAGE_MAX = 100


class AgentUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    persona: str | None = Field(default=None, max_length=4000)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=600)
    kind: str = Field(default="fact", pattern="^(fact|preference|decision|summary)$")


class ToolsUpdate(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)


@router.get("", dependencies=[Depends(_rate_limit)])
async def get_my_agent(
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """My agent, created on first read.

    Created here rather than only on first chat so the panel has something to
    show a user who has never sent a message.
    """
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)
    stats = await agent_memory.agent_stats(session, auth.organization.id, auth.user.id)
    return ok(agent_payload(agent, stats))


@router.patch("", dependencies=[Depends(_rate_limit)])
async def update_my_agent(
    body: AgentUpdate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Change persona / display name.

    The persona is *additive* to the organization's grounding prompt - it is
    appended, never substituted, so a user cannot edit away the citation rules
    or the safety instructions by writing a persona that contradicts them.
    """
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)
    changed = await update_agent_settings(
        session, agent, display_name=body.display_name, persona=body.persona
    )
    if changed:
        await record_audit(
            session,
            "agent.updated",
            organization_id=auth.organization.id,
            actor_user_id=auth.user.id,
            entity_type="user_agent",
            entity_id=agent.id,
            detail={"fields": changed},
        )
    stats = await agent_memory.agent_stats(session, auth.organization.id, auth.user.id)
    return ok(agent_payload(agent, stats))


@router.get("/memory", dependencies=[Depends(_rate_limit)])
async def list_my_memory(
    kind: str | None = None,
    active: bool = True,
    limit: int = Query(default=50, ge=1, le=MEMORY_PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """What my agent remembers. Ordered by weight then recency, so the memories
    that actually shape its behaviour are the ones shown first."""
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)

    filters = [
        AgentMemory.agent_id == agent.id,
        AgentMemory.active.is_(active),
    ]
    if kind:
        filters.append(AgentMemory.kind == kind)

    total = (
        await session.execute(select(func.count()).select_from(AgentMemory).where(*filters))
    ).scalar_one()
    rows = (
        await session.execute(
            select(AgentMemory)
            .where(*filters)
            .order_by(desc(AgentMemory.weight), desc(AgentMemory.created_at))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return ok(
        {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "memories": [
                {
                    "id": str(memory.id),
                    "kind": memory.kind,
                    "content": memory.content,
                    "weight": round(float(memory.weight), 3),
                    "hits": memory.hits,
                    "misses": memory.misses,
                    "active": memory.active,
                    "created_at": memory.created_at,
                }
                for memory in rows
            ],
        }
    )


@router.post("/memory", dependencies=[Depends(_rate_limit)])
async def create_memory(
    body: MemoryCreate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Teach the agent something directly.

    A memory the user typed starts at full weight, same as one the extraction
    inferred: the only difference is provenance, and this one is not a guess.
    """
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)

    from backend.knowledge.embeddings import embed_one

    try:
        vector = await embed_one(body.content)
    except Exception:  # noqa: BLE001 - storing without a vector is better than not storing
        vector = None

    memory = AgentMemory(
        organization_id=auth.organization.id,
        user_id=auth.user.id,
        agent_id=agent.id,
        kind=body.kind,
        content=body.content,
        weight=1.0,
        active=True,
        embedding=vector,
    )
    session.add(memory)
    await session.flush()
    # Same reason as update_agent_settings: created_at comes from the server
    # default and is expired after the INSERT, so it must be loaded before the
    # payload below reads it.
    await session.refresh(memory)
    await record_audit(
        session,
        "agent.memory.created",
        organization_id=auth.organization.id,
        actor_user_id=auth.user.id,
        entity_type="agent_memory",
        entity_id=memory.id,
        detail={"kind": body.kind, "source": "user"},
    )
    return ok({"id": str(memory.id), "kind": memory.kind, "content": memory.content})


@router.delete("/memory/{memory_id}", dependencies=[Depends(_rate_limit)])
async def forget_memory(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Forget one memory. This is the only hard delete of a memory, and it is
    the user's own explicit action - the learning loop only ever deactivates."""
    removed = await agent_memory.forget(
        session, auth.organization.id, auth.user.id, memory_id
    )
    if not removed:
        raise ApiError(404, "MEMORY_NOT_FOUND", "That memory does not exist.")
    await record_audit(
        session,
        "agent.memory.deleted",
        organization_id=auth.organization.id,
        actor_user_id=auth.user.id,
        entity_type="agent_memory",
        entity_id=memory_id,
    )
    return ok({"deleted": True})


@router.get("/tools", dependencies=[Depends(_rate_limit)])
async def list_my_tools(
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """The tool catalogue plus whether this agent may use each one.

    An empty allowlist means "all", which is the default for a fresh agent - so
    it is reported as enabled rather than as an empty toolbox.
    """
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)
    allowed = set(agent.allowed_tools or [])
    tools = [
        {
            "name": spec.name,
            "description": spec.description,
            "enabled": (not allowed) or spec.name in allowed,
            "writes": spec.writes,
        }
        for spec in tool_registry.all_specs()
    ]
    return ok({"tools": tools, "allowlist": sorted(allowed), "unrestricted": not allowed})


@router.patch("/tools", dependencies=[Depends(_rate_limit)])
async def set_my_tools(
    body: ToolsUpdate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Set the tool allowlist.

    Unknown names are rejected rather than stored: a typo would silently disable
    a tool, and the user would have no way to see why their reports stopped
    working.
    """
    known = {spec.name for spec in tool_registry.all_specs()}
    unknown = sorted(set(body.allowed_tools) - known)
    if unknown:
        raise ApiError(
            422, "UNKNOWN_TOOL", "Unknown tool(s): " + ", ".join(unknown)
        )

    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)
    agent.allowed_tools = sorted(set(body.allowed_tools))
    await session.flush()
    await record_audit(
        session,
        "agent.tools.updated",
        organization_id=auth.organization.id,
        actor_user_id=auth.user.id,
        entity_type="user_agent",
        entity_id=agent.id,
        detail={"allowed_tools": agent.allowed_tools},
    )
    return ok({"allowlist": agent.allowed_tools})


@router.get("/activity", dependencies=[Depends(_rate_limit)])
async def my_activity(
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """My agent's recent tool calls.

    Scoped by user_id, so this shows what *my* agent did. The same rows are
    visible to the admin panel scoped by organization - this is the user's half
    of the trace the PO asked for.
    """
    rows = (
        await session.execute(
            select(AgentToolInvocation)
            .where(
                AgentToolInvocation.organization_id == auth.organization.id,
                AgentToolInvocation.user_id == auth.user.id,
            )
            .order_by(desc(AgentToolInvocation.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return ok(
        {
            "invocations": [
                {
                    "id": str(row.id),
                    "tool_name": row.tool_name,
                    "ok": row.ok,
                    "duration_ms": row.duration_ms,
                    "round_index": row.round_index,
                    "asset_id": str(row.asset_id) if row.asset_id else None,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        }
    )
