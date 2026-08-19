"""Shared auth dependency for session-scoped endpoints (wave 2+).

Resolves the HttpOnly ``session`` cookie (issued in US-002) to its owning
Organization. Every protected onboarding endpoint (US-004 workspaces/initialize,
US-005 brain/initialize, later US-007/US-008) depends on this instead of
re-implementing cookie → session → org resolution.
"""

from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import UnauthorizedError
from app.models import Organization
from app.services import session_service

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def require_org_session(
    session: DbSession,
    session_cookie: Annotated[str | None, Cookie(alias="session")] = None,
) -> Organization:
    """Resolve the session cookie to a live Session, then to its Organization.

    Raises 401 when the cookie is missing, invalid, expired or revoked — the
    caller gets a scoped Organization object to work with.
    """
    row = await session_service.resolve_session(session, session_cookie)
    if row is None:
        raise UnauthorizedError("a valid session is required")

    org = await session.get(Organization, row.organization_id)
    if org is None:
        raise UnauthorizedError("organization not found for session")
    return org