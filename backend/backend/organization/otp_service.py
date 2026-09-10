"""OTP send/resend service (US-003, T-S1-3).

State machine per US-003 Amendment 2: 6-digit code, TTL 5 minutes, max 5
failed attempts (enforced at verify time, T-S1-4), resend cooldown 60s,
15-minute lockout after exhausted attempts. All parameters come from
settings (admin-configurable later via US-1605).

Security (US-003 security requirements): crypto-secure generation, only
SHA-256 digests stored, digest binds the user id, one active code per
(user, purpose), replay prevented by consumption at verify time.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.db import session_factory
from backend.models import OtpVerification, User
from backend.sms import SmsDeliveryError, get_sms_provider

PURPOSE_OWNER_VERIFICATION = "owner_verification"
PURPOSE_PASSWORD_RESET = "password_reset"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def generate_code() -> str:
    """6-digit, numeric-only, crypto-secure (US-003 OTP rules)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def code_digest(user_id, code: str) -> str:
    """SHA-256 hex of the code bound to the user id (blocks precomputed tables)."""
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


async def _latest_otp(
    session: AsyncSession, user_id, purpose: str
) -> OtpVerification | None:
    return (
        await session.execute(
            select(OtpVerification)
            .where(
                OtpVerification.user_id == user_id,
                OtpVerification.purpose == purpose,
            )
            .order_by(OtpVerification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _active_otp(session: AsyncSession, user_id, purpose: str) -> OtpVerification | None:
    return (
        await session.execute(
            select(OtpVerification).where(
                OtpVerification.user_id == user_id,
                OtpVerification.purpose == purpose,
                OtpVerification.consumed_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _record_delivery_failure(user: User, reason: str) -> None:
    """US-003 scenario 5: the delivery-failure event must survive the failed
    request, so it is written in its own committed transaction."""

    async with session_factory() as audit_session:
        await record_audit(
            audit_session,
            "otp.delivery_failed",
            actor_user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            detail={"mobile": user.mobile, "reason": reason},
        )
        await audit_session.commit()


async def send_otp(
    session: AsyncSession, user: User, *, purpose: str, event: str
) -> dict:
    """Common send/resend path. event: 'otp.sent' or 'otp.resent'."""
    settings = get_settings()
    now = _utc_now()

    if user.mobile_verified:
        raise ApiError(409, "MOBILE_ALREADY_VERIFIED", "This mobile number is already verified.")

    active = await _active_otp(session, user.id, purpose)
    if active is not None and active.locked_until is not None and active.locked_until > now:
        raise ApiError(
            429,
            "OTP_LOCKED",
            "OTP requests for this number are temporarily locked. Try again later.",
        )

    latest = await _latest_otp(session, user.id, purpose)
    if latest is not None:
        cooldown_ready = latest.created_at + timedelta(seconds=settings.otp_resend_cooldown_seconds)
        if now < cooldown_ready:
            raise ApiError(
                429,
                "OTP_COOLDOWN",
                "Please wait before requesting a new code.",
            )

    code = generate_code()
    expires_at = now + timedelta(seconds=settings.otp_ttl_seconds)
    if active is not None:
        # Sending a new code invalidates the previous one (one active per user+purpose).
        active.consumed_at = now

    otp_row = OtpVerification(
        user_id=user.id,
        mobile=user.mobile,
        code_hash=code_digest(user.id, code),
        purpose=purpose,
        expires_at=expires_at,
    )
    session.add(otp_row)
    await session.flush()

    try:
        await get_sms_provider().send_otp(user.mobile, code)
    except SmsDeliveryError as exc:
        # US-003 FR-007 / scenario 5: explicit failure, clear message, event recorded.
        await _record_delivery_failure(user, str(exc))
        raise ApiError(
            503,
            "SMS_DELIVERY_FAILED",
            "Server cannot reach the SMS gateway. Internet access is required to complete registration.",
        ) from exc

    await record_audit(
        session,
        event,
        actor_user_id=user.id,
        entity_type="otp_verification",
        entity_id=otp_row.id,
        detail={"purpose": purpose, "mobile": user.mobile},
    )
    return {
        "expires_at": expires_at,
        "resend_available_at": now + timedelta(seconds=settings.otp_resend_cooldown_seconds),
    }
