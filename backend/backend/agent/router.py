"""User-facing agent endpoints (PO 2026-09): my agent, my memory, my tools.

Everything here is scoped to the *authenticated user inside their organization*.
There is deliberately no "get agent by id" route: a per-user agent is reachable
only as "mine", so a guessed uuid cannot read someone else's memory. The
organization_id and user_id always come from the auth context, never the path.

What the user can do:

  GET    /agent                  - my agent: status, memory stats
  PATCH  /agent                  - change my display name
  GET    /agent/memory           - what my agent remembers (paged, filterable)
  POST   /agent/memory           - teach it something explicitly
  DELETE /agent/memory/{id}      - forget one memory
  GET    /agent/tools            - the organization's tool catalogue (read-only)
  GET    /agent/activity         - my recent tool calls (the trace)

WHAT THE USER OWNS HERE. Identity and state: how they refer to their agent, what
it remembers about them, and whether a memory is forgotten. The memory itself is
personal - it is what the agent learned about this person - so teaching and
forgetting stay user-facing.

WHAT THE ORGANIZATION OWNS. Behaviour: persona and the tool allowlist. Those are
admin-panel settings (the "agent" key, alongside the prompt template and
provider config) because the agent answers on the organization's behalf, and one
member must not change the voice or the capabilities everyone else gets. The
user-facing PATCH routes that used to set them either reject the field or explain
why they are refused.

The activity route is the user's window into the same trace the admin panel
reads: the PO asked that every action be traceable, and the person best placed
to notice a wrong action is the one who asked for it.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
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
    """What a user may change about their own agent.

    Only the display name. Persona and the tool allowlist moved to the
    organization-wide "agent" setting (admin panel): they decide how the agent
    answers, and the answer is the organization's, so one member must not be able
    to change the voice or the capabilities every other member gets.

    The field is typed Optional with a default of None and the extra is rejected
    rather than ignored: silently accepting a persona here and discarding it
    would look like the setting saved.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=120)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=600)
    kind: str = Field(default="fact", pattern="^(fact|preference|decision|summary)$")


class ToolsUpdate(BaseModel):
    """Retained only so the refusal below has a typed body to parse.

    The route is refused unconditionally, so this model never carries a decision
    anywhere - it exists so a client sending the old payload gets the explanatory
    403 rather than a schema error about the shape of a request it was built for.
    """

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
    """Change how this user refers to their agent.

    The display name only. Persona and the tool allowlist are organization-level
    (see AgentUpdate) - the agent answers on the organization's behalf, so its
    voice and capabilities are not a personal preference. The request model
    rejects those fields rather than ignoring them.
    """
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)
    changed = await update_agent_settings(
        session, agent, display_name=body.display_name
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
    """The tool catalogue plus whether the organization enables each one.

    Read-only: the allowlist is an organization setting set in the admin panel,
    so this reports what the org decided rather than what this user chose. The
    user can still see their own capabilities, which is the point of the route.

    An empty allowlist means "all", so it is reported as enabled rather than as
    an empty toolbox.
    """
    agent = await agent_memory.ensure_agent(session, auth.organization.id, auth.user.id)
    from backend.agent.service import tools_for

    settings = await agent_memory.agent_settings(session)
    allowed = set(tools_for(agent, settings))
    tools = [
        {
            "name": spec.name,
            "description": spec.description,
            "enabled": (not allowed) or spec.name in allowed,
            "writes": spec.writes,
        }
        for spec in tool_registry.all_specs()
    ]
    return ok(
        {
            "tools": tools,
            "allowlist": sorted(allowed),
            "unrestricted": not allowed,
            # Says plainly why PATCH no longer exists, so the frontend can show
            # the reason instead of a dead control.
            "managed_by": "organization",
        }
    )


@router.patch("/tools", dependencies=[Depends(_rate_limit)])
async def set_my_tools(
    body: ToolsUpdate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Refused: the tool allowlist is an organization setting.

    Kept as a route that explains itself rather than deleted, so a client built
    against the old contract gets a reason it can show instead of a bare 405. A
    user must not be able to grant themselves capabilities the organization
    withheld - the agent acts on the organization's behalf.
    """
    raise ApiError(
        403,
        "AGENT_SETTINGS_MANAGED_BY_ORGANIZATION",
        "تنظیمات ابزارهای دستیار در سطح سازمان تعیین می‌شود.",
    )


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
