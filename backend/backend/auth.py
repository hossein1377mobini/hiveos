"""Bearer session authentication (US-002 FR-004, IAM section 7).

The frontend sends the opaque token issued at owner creation / login as
'Authorization: Bearer <token>'. Only the SHA-256 digest is looked up.
Sliding window (IAM section 7): every authenticated request extends the
session expiry to a full fresh TTL.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.config import get_settings
from backend.db import get_db
from backend.models import Organization, User
from backend.models import Session as DbSession


@dataclass(slots=True)
class AuthContext:
    token: str
    session: DbSession
    user: User
    organization: Organization


async def get_auth_context(
    request: Request, db: AsyncSession = Depends(get_db, scope="function")
) -> AuthContext:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "AUTH_REQUIRED", "Authentication required.")
    token = header.removeprefix("Bearer ").strip()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session_row = (
        await db.execute(select(DbSession).where(DbSession.token_hash == token_hash))
    ).scalar_one_or_none()
    if session_row is None:
        raise ApiError(401, "AUTH_REQUIRED", "Authentication required.")
    if session_row.revoked_at is not None:
        raise ApiError(401, "SESSION_REVOKED", "Session is no longer valid.")
    if session_row.expires_at <= datetime.now(UTC):
        raise ApiError(401, "SESSION_EXPIRED", "Session has expired.")

    # IAM section 7: 7-day sliding window - every authenticated request slides
    # the expiry to a full fresh TTL. Persisted by the request-scoped
    # transaction (backend.db.get_db commit-on-success).
    session_row.expires_at = datetime.now(UTC) + timedelta(days=get_settings().session_ttl_days)

    user = await db.get(User, session_row.user_id)
    organization = await db.get(Organization, session_row.organization_id)
    if user is None or organization is None:
        raise ApiError(401, "AUTH_REQUIRED", "Authentication required.")
    return AuthContext(token=token, session=session_row, user=user, organization=organization)
