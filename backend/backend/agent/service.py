"""Agent service: payload shaping and settings, shared by the user and admin
surfaces.

Kept apart from memory.py so the extraction/retrieval logic can be tested and
reasoned about without the API's view of an agent. Both callers - the user's
/agent routes and the admin panel - read the same payload builder, which is what
stops the two panels drifting apart in what they report.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import UserAgent

# What a fresh agent's persona is. Left empty on purpose: the organization
# brain already carries the grounding rules, and a default persona would be a
# second voice competing with it. The user adds one if they want one.
DEFAULT_PERSONA = ""

PERSONA_MAX = 4000


def agent_payload(agent: UserAgent, stats: dict | None = None) -> dict:
    """One agent, as both panels display it."""
    payload = {
        "id": str(agent.id),
        "organization_id": str(agent.organization_id),
        "user_id": str(agent.user_id),
        "brain_id": str(agent.brain_id) if agent.brain_id else None,
        "display_name": agent.display_name,
        "persona": agent.persona,
        "allowed_tools": list(agent.allowed_tools or []),
        "settings": dict(agent.settings or {}),
        "status": agent.status,
        "version": agent.version,
        "last_active_at": agent.last_active_at,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }
    if stats is not None:
        payload["memory"] = stats
    return payload


async def update_agent_settings(
    session: AsyncSession,
    agent: UserAgent,
    *,
    display_name: str | None = None,
    persona: str | None = None,
) -> list[str]:
    """Apply a partial update.

    None means "not supplied" and leaves the field alone, so a caller that only
    sends a persona cannot blank the display name - the difference between a
    PATCH and a PUT, enforced here rather than trusted from the client.
    """
    changed: list[str] = []
    if display_name is not None and display_name != agent.display_name:
        agent.display_name = display_name.strip()[:120]
        changed.append("display_name")
    if persona is not None and persona != agent.persona:
        # Clamped, not rejected: a persona that is too long is a small problem,
        # and silently truncating is friendlier than a 422 on a free-text field.
        agent.persona = persona.strip()[:PERSONA_MAX]
        changed.append("persona")
    if changed:
        # version increments so a cached prompt can be invalidated and so the
        # admin panel can see that behaviour changed at a known point.
        agent.version = (agent.version or 1) + 1
        await session.flush()
        # The UPDATE carries updated_at's onupdate=now(), which expires the
        # attribute; any later read of the row (the payload builder always
        # reads updated_at) would then attempt a lazy load and raise
        # MissingGreenlet under async. Refresh eagerly, here, so every caller
        # gets a fully-loaded object instead of each one rediscovering this.
        await session.refresh(agent)
    return changed
