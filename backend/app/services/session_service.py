"""Minimal owner-session helpers (US-002).

Only the SHA-256 hash of a session token is ever stored; the raw token is
returned to the caller once (to set the cookie) and never persisted or logged.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.config import get_settings
from app.models import Session


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of the raw token (the only representation we store)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _default_expiry() -> datetime:
    ttl = get_settings().session_ttl_seconds
    return datetime.now(UTC) + timedelta(seconds=ttl)


async def issue_session(
    session: AsyncSession,
    *,
    owner_id,
    tenant_id,
    organization_id,
) -> tuple[str, Session]:
    """Issue a session row; returns ``(raw_token, session_row)``. Caller commits."""
    raw_token = security.new_session_token()
    row = Session(
        token_hash=hash_token(raw_token),
        owner_id=owner_id,
        tenant_id=tenant_id,
        organization_id=organization_id,
        expires_at=_default_expiry(),
    )
    session.add(row)
    return raw_token, row


async def resolve_session(session: AsyncSession, raw_token: str | None) -> Session | None:
    """Resolve a raw token to a live (non-expired) Session row, or None."""
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    result = await session.execute(
        select(Session).where(
            Session.token_hash == token_hash,
            Session.expires_at > datetime.now(UTC),
        )
    )
    return result.scalar_one_or_none()
