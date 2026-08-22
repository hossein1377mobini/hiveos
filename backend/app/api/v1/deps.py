"""Shared auth dependency for session-scoped endpoints (wave 2+).

Resolves the HttpOnly ``session`` cookie (issued in US-002) to its owning
Organization. Every protected onboarding endpoint (US-004 workspaces/initialize,
US-005 brain/initialize, later US-007/US-008) depends on this instead of
re-implementing cookie → session → org resolution.
"""

from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.config import get_settings
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


def client_ip(request: Request) -> str:
    """Socket peer IP used as the rate-limit key for unauthenticated endpoints.

    MVP: we trust only the transport peer (``request.client.host``). We
    deliberately do NOT read ``X-Forwarded-For`` from the open internet — it is
    attacker-controllable and must only be honoured behind an explicit
    trusted-proxy allowlist (FASTAPI-PROXY-001). When behind a reverse proxy
    in production, configure Uvicorn ``--proxy-headers`` with
    ``--forwarded-allow-ips`` restricted to that proxy.
    """
    client = getattr(request, "client", None)
    return (client.host if client else None) or "unknown"


async def enforce_registration_ip_limit(request: Request) -> None:
    """S1-12: per-IP budget for the unauthenticated signup endpoints.

    Guards ``/organizations`` and ``/users/owner`` where no account identity
    exists yet. PBKDF2-600k password hashing is deliberately CPU-expensive, so
    an unauthenticated caller must not be able to sink arbitrary CPU by
    hammering these routes.
    """
    s = get_settings()
    await ratelimit.enforce_ip_limit(
        ip=client_ip(request),
        bucket="registration",
        limit=s.ip_rate_limit_registration,
        window_seconds=s.rate_window_seconds,
    )


async def enforce_otp_send_ip_limit(request: Request) -> None:
    """S1-12: per-IP budget for OTP send/resend (SMS cost / flood vector)."""
    s = get_settings()
    await ratelimit.enforce_ip_limit(
        ip=client_ip(request),
        bucket="otp:send",
        limit=s.ip_rate_limit_otp_send,
        window_seconds=s.rate_window_seconds,
    )
