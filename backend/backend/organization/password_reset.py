"""Password reset via OTP-SMS (US-010, T-S1-6).

Three-step flow with generic responses everywhere (no account disclosure):

1. reset-request  {mobile}   -> sends a password_reset OTP (or stays silent)
2. reset-verify   {mobile, code} -> checks the code WITHOUT consuming it
3. reset          {mobile, code, new_password, confirm_password}
   -> validates the policy, consumes the OTP, hashes the new password and
   revokes every active session of the account (FR-004).

Attempt counting / locking reuses the US-003 state machine
(organization.otp_verify.check_active_otp), so the 5-attempt / 15-minute
lockout applies per code as configured via US-1605 settings.

Transaction note: the new password, the OTP consumption and the session
revocations happen in the request transaction; the failure events on the
attempt paths persist through the audit-engine pattern of US-003.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.models import Session, User
from backend.organization.otp_service import PURPOSE_PASSWORD_RESET, send_otp
from backend.organization.otp_verify import check_active_otp
from backend.organization.schemas import normalize_mobile
from backend.security import hash_password, password_policy_violations

_GENERIC_REQUEST_MESSAGE = "If the mobile number is registered, a reset code has been sent."


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _find_user_by_mobile(session: AsyncSession, mobile: str) -> User | None:
    return (
        await session.execute(select(User).where(User.mobile == mobile))
    ).scalar_one_or_none()


async def send_reset_request(session: AsyncSession, mobile: str) -> dict:
    """US-010 scenario 3: unknown mobiles get the same generic response."""
    settings = get_settings()
    canonical = normalize_mobile(mobile)
    user = await _find_user_by_mobile(session, canonical)

    now = _utc_now()
    generic = {
        "message": _GENERIC_REQUEST_MESSAGE,
        "expires_at": (now + timedelta(seconds=settings.otp_ttl_seconds)).isoformat(),
        "resend_available_at": (
            now + timedelta(seconds=settings.otp_resend_cooldown_seconds)
        ).isoformat(),
    }
    if user is None:
        # No OTP row, no SMS, no user-specific audit detail (no disclosure).
        return generic

    await record_audit(
        session,
        "password.reset.requested",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    await send_otp(
        session, user, purpose=PURPOSE_PASSWORD_RESET, event="otp.sent", require_unverified=False
    )
    return generic


async def verify_reset_code(session: AsyncSession, mobile: str, code: str) -> dict:
    """US-010: the check step - identical errors never reveal account state."""
    canonical = normalize_mobile(mobile)
    user = await _find_user_by_mobile(session, canonical)
    if user is None:
        # Same code/message family as a wrong code, but no counter to show.
        raise ApiError(400, "OTP_INVALID", "Invalid code or request.")
    await check_active_otp(session, user.id, PURPOSE_PASSWORD_RESET, code)
    await record_audit(
        session,
        "otp.verified",
        actor_user_id=user.id,
        entity_type="password_reset",
        entity_id=user.id,
        detail={"stage": "verify"},
    )
    return {"verified": True}


async def reset_password(
    session: AsyncSession, mobile: str, code: str, new_password: str, confirm_password: str
) -> dict:
    """US-010 scenario 1: set the new password, revoke all active sessions."""
    if new_password != confirm_password:
        raise ApiError(400, "PASSWORD_MISMATCH", "Password and confirmation do not match.")
    violations = password_policy_violations(new_password)
    if violations:
        raise ApiError(
            400, "PASSWORD_POLICY", "Password does not meet the policy: " + ", ".join(violations)
        )

    canonical = normalize_mobile(mobile)
    user = await _find_user_by_mobile(session, canonical)
    if user is None:
        raise ApiError(400, "OTP_INVALID", "Invalid code or request.")

    active = await check_active_otp(session, user.id, PURPOSE_PASSWORD_RESET, code)
    now = _utc_now()

    # One-time use: consume the OTP with the reset (FR-004).
    active.consumed_at = now
    user.password_hash = hash_password(new_password)

    result = await session.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    revoked = result.rowcount or 0

    await record_audit(
        session,
        "otp.verified",
        actor_user_id=user.id,
        entity_type="otp_verification",
        entity_id=active.id,
        detail={"stage": "reset"},
    )
    await record_audit(
        session,
        "password.reset.completed",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        detail={"sessions_revoked": revoked},
    )
    return {"password_reset": True, "sessions_revoked": revoked}
