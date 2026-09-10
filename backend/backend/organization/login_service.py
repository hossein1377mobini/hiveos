"""Login + logout service (US-009, T-S1-5).

Lockout state machine: 5 failed username+password attempts lock the account
for 15 minutes (Amendment 2; admin-configurable later via US-1605). The
failed-attempt counter is per account and resets on success and after the
lock expires. Error messages never disclose which field was wrong.

Transaction note: a failed login ends its request with ApiError, so the
attempt increment and lock events are written through the NullPool audit
engine in their own committed transaction (same pattern as OTP attempts).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.db import audit_session_factory
from backend.models import LoginAttempt, Organization, User
from backend.models import Session as DbSession
from backend.security import new_session_token, verify_password

# Argon2 digest of an unguessable random value: verifying against it for
# unknown usernames keeps response timing roughly uniform (no user enum).
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$ZXhhbXBsZXNhbHRleGFtcGxl$QW5PVGR1bW15VmFsdWVGb3JUaW1pbmdPbmx5UGFkZGluZw"


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _find_user(session: AsyncSession, username: str) -> User | None:
    return (
        await session.execute(
            select(User).where(func.lower(User.username) == username.strip().lower())
        )
    ).scalar_one_or_none()


async def _resolve_organization_id(session: AsyncSession, user: User) -> uuid.UUID | None:
    from backend.models import OrganizationMember

    member_org = (
        await session.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == user.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if member_org is not None:
        return member_org
    return (
        await session.execute(
            select(Organization.id).where(Organization.owner_user_id == user.id).limit(1)
        )
    ).scalar_one_or_none()


async def _record_failed_attempt(user: User | None, username_attempted: str) -> tuple[int, bool]:
    """Increment the per-account counter (and lock at the max) in a committed
    transaction. Returns (attempts, locked)."""
    settings = get_settings()

    async with audit_session_factory() as audit_session:
        target: User | None = None
        if user is not None:
            target = await audit_session.get(User, user.id, with_for_update=True)
        attempts = (target.failed_login_count if target else 0) + 1
        locked = attempts >= settings.login_max_attempts
        if target is not None:
            target.failed_login_count = attempts
            if locked:
                target.locked_until = datetime.now(UTC) + timedelta(
                    seconds=settings.login_lockout_seconds
                )
        audit_session.add(
            LoginAttempt(
                user_id=user.id if user else None,
                username_attempted=username_attempted[:50],
                successful=False,
            )
        )
        if locked and target is not None:
            await record_audit(
                audit_session,
                "auth.account.locked",
                actor_user_id=target.id,
                entity_type="user",
                entity_id=target.id,
                detail={"attempts": attempts},
            )
        await audit_session.commit()
        return attempts, locked


async def login(session: AsyncSession, username: str, password: str) -> dict:
    """US-009 FR-001/FR-002: username+password login with per-account lockout."""
    settings = get_settings()
    user = await _find_user(session, username)

    if user is None:
        verify_password(_DUMMY_HASH, password)  # timing equalization
        await _record_failed_attempt(None, username)
        raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "Invalid username or password.")

    if user.locked_until is not None and user.locked_until > _utc_now():
        remaining = max(0, int((user.locked_until - _utc_now()).total_seconds()) + 1)
        minutes = max(1, remaining // 60)
        raise ApiError(
            429,
            "ACCOUNT_LOCKED",
            f"Account is locked after too many failed attempts. Try again in ~{minutes} minute(s).",
        )

    if user.password_hash is None or not verify_password(user.password_hash, password):
        attempts, locked = await _record_failed_attempt(user, user.username)
        if locked:
            raise ApiError(
                429,
                "ACCOUNT_LOCKED",
                "Account is locked after too many failed attempts.",
            )
        remaining = settings.login_max_attempts - attempts
        raise ApiError(
            401,
            "AUTH_INVALID_CREDENTIALS",
            f"Invalid username or password. Remaining attempts: {remaining}.",
        )

    # Success: reset the counter, create the 7-day sliding session (FR-004).
    user.failed_login_count = 0
    user.locked_until = None

    organization_id = await _resolve_organization_id(session, user)
    if organization_id is None:
        # v0.1 contract: every login user belongs to an organization (IAM section 7).
        raise ApiError(403, "NO_ORGANIZATION", "No organization is linked to this account.")

    token, token_hash = new_session_token()
    expires_at = _utc_now() + timedelta(days=settings.session_ttl_days)
    session_row = DbSession(
        token_hash=token_hash,
        user_id=user.id,
        organization_id=organization_id,
        expires_at=expires_at,
    )
    session.add(session_row)
    await session.flush()

    await record_audit(
        session,
        "auth.login.succeeded",
        organization_id=organization_id,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    await record_audit(
        session,
        "session.created",
        organization_id=organization_id,
        actor_user_id=user.id,
        entity_type="session",
        entity_id=session_row.id,
        detail={"expires_at": expires_at.isoformat()},
    )
    session.add(
        LoginAttempt(user_id=user.id, username_attempted=user.username[:50], successful=True)
    )

    return {
        "user_id": user.id,
        "organization_id": organization_id,
        "session": {"token": token, "expires_at": expires_at},
    }


async def logout(session: AsyncSession, auth_session: DbSession) -> None:
    """US-009: revoke the current session; the token becomes unusable."""
    auth_session.revoked_at = _utc_now()
    await record_audit(
        session,
        "session.expired",
        organization_id=auth_session.organization_id,
        actor_user_id=auth_session.user_id,
        entity_type="session",
        entity_id=auth_session.id,
    )
