"""Agent service: payload shaping and settings, shared by the user and admin
surfaces.

Kept apart from memory.py so the extraction/retrieval logic can be tested and
reasoned about without the API's view of an agent. Both callers - the user's
/agent routes and the admin panel - read the same payload builder, which is what
stops the two panels drifting apart in what they report.

WHO DECIDES THE AGENT'S BEHAVIOUR. The organization does, through the admin
panel's "agent" setting (see memory.agent_settings and admin.AgentSettingsSchema),
because the agent answers on the organization's behalf and its output is
attributed to the organization. A per-user persona and per-user tool allowlist
were editable from the user's own page and are now organization-level.

What stays per-user on this object is identity and state, not policy:
display_name is how the person refers to their assistant, and the memory tables
are what it has learned about them.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import UserAgent

PERSONA_MAX = 4000


def persona_for(agent: UserAgent, organization_settings: dict) -> str:
    """The persona in force: the organization's, not the user's.

    Kept as a function so the precedence is stated in exactly one place. Any
    per-user persona already stored is returned only when the organization has
    not set one, so an existing row cannot silently outrank an org decision -
    and nothing new can set a per-user persona, because the user-facing PATCH no
    longer accepts one.
    """
    organization_persona = str(organization_settings.get("persona") or "").strip()
    if organization_persona:
        return organization_persona
    return str(agent.persona or "").strip()


def tools_for(agent: UserAgent, organization_settings: dict) -> list[str]:
    """The tool allowlist in force. Organization-level, like the persona.

    An empty list means every tool, which is the same convention execution
    already used.
    """
    allowed = organization_settings.get("allowed_tools")
    if allowed:
        return list(allowed)
    return list(agent.allowed_tools or [])


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
