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
    # The organization's Owner. This is the product's "admin" of an
    # organization: PO requirement 2026-09 - "knowledge is collected across the
    # whole organization, access is by level", and the level above "member" is
    # the Owner, who reads every file in the organization regardless of owner.
    # Derived from organizations.owner_user_id - the column that already
    # identifies the owner (there is one owner per organization, DB-enforced by
    # uq_organizations_owner_user_id, migration 0023). It is NOT a role check:
    # nothing in the request path resolves role_assignments, and inventing a
    # second source of truth for "who is the admin" is how the two drift apart.
    is_admin: bool = False


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
    # PO 2026-09: the organization's Owner (organizations.owner_user_id) reads
    # the whole organization's knowledge. Everyone else reads their own files
    # plus the org-wide ones - see knowledge/assets.visible_to.
    is_admin = organization.owner_user_id is not None and organization.owner_user_id == user.id
    return AuthContext(
        token=token,
        session=session_row,
        user=user,
        organization=organization,
        is_admin=is_admin,
    )
