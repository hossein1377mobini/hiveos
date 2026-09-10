"""OTP verification service (US-003, T-S1-4).

Completes the US-003 state machine started in T-S1-3: wrong code counts
attempts (FR-004), 5 failed attempts lock the request for 15 minutes
(scenario 4 / Amendment 2), correct code activates the owner and the
organization (FR-003), the code is consumed immediately (FR-006), and the
session slides to a fresh 7-day expiry (IAM section 7, done in
backend.auth.get_auth_context).

Transaction note: failed-attempt counting and the expired-code event must
survive the failing request (FR-004 / FR-005), so they are written in their
own committed transactions - same pattern as otp.delivery_failed in
otp_service.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.db import audit_session_factory
from backend.models import Organization
from backend.models.enums import OrganizationStatus
from backend.models.otp import OtpVerification
from backend.models.user import User
from backend.organization.otp_service import PURPOSE_OWNER_VERIFICATION, _active_otp, _utc_now, code_digest


async def _record_failed_attempt(user_id, otp_id: object) -> tuple[int, bool]:
    """Increment attempts (and lock at the max) in a committed transaction.

    Returns (attempts, locked). SELECT ... FOR UPDATE keeps concurrent
    verifies from losing increments.
    """
    settings = get_settings()

    async with audit_session_factory() as audit_session:
        row = await audit_session.get(OtpVerification, otp_id, with_for_update=True)
        assert row is not None  # the main transaction just selected it
        row.failed_attempts = (row.failed_attempts or 0) + 1
        locked = row.failed_attempts >= settings.otp_max_attempts
        if locked:
            row.locked_until = datetime.now(UTC) + timedelta(seconds=settings.otp_lockout_seconds)
        await record_audit(
            audit_session,
            "otp.locked" if locked else "otp.failed",
            actor_user_id=user_id,
            entity_type="otp_verification",
            entity_id=otp_id,
            detail={"attempts": row.failed_attempts},
        )
        await audit_session.commit()
        return row.failed_attempts, locked


async def _record_expired(user_id, otp_id: object) -> None:
    async with audit_session_factory() as audit_session:
        await record_audit(
            audit_session,
            "otp.expired",
            actor_user_id=user_id,
            entity_type="otp_verification",
            entity_id=otp_id,
        )
        await audit_session.commit()


def _status_value(status) -> str:
    return status.value if isinstance(status, OrganizationStatus) else str(status)


async def check_active_otp(
    session: AsyncSession, user_id, purpose: str, code: str, *, not_found_code: str = "OTP_NOT_FOUND",
) -> OtpVerification:
    """Shared US-003 state machine: locked / expired / wrong-code handling.

    Raises ApiError on every failure path (attempt counting persists via the
    audit engine); returns the active row on success WITHOUT consuming it.
    """
    settings = get_settings()
    now = _utc_now()

    active: OtpVerification | None = await _active_otp(session, user_id, purpose)
    if active is None:
        raise ApiError(404, not_found_code, "No active code. Request a new one.")
    if active.locked_until is not None and active.locked_until > now:
        raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Try again later.")
    if active.expires_at <= now:
        # FR-005: expired -> reject, state untouched, resend remains possible.
        await _record_expired(user_id, active.id)
        raise ApiError(410, "OTP_EXPIRED", "This code has expired. Request a new one.")

    if code_digest(user_id, code) != active.code_hash:
        attempts, locked = await _record_failed_attempt(user_id, active.id)
        if locked:
            raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Try again later.")
        remaining = settings.otp_max_attempts - attempts
        raise ApiError(400, "OTP_INVALID", f"Wrong code. Remaining attempts: {remaining}.")
    return active


async def verify_otp(
    session: AsyncSession, user: User, organization: Organization, code: str
) -> dict:
    """Validate 'code' for the active owner-verification OTP of 'user'."""
    now = _utc_now()

    if user.mobile_verified:
        raise ApiError(409, "MOBILE_ALREADY_VERIFIED", "This mobile number is already verified.")

    active = await check_active_otp(session, user.id, PURPOSE_OWNER_VERIFICATION, code)

    # FR-006: consume immediately - no replay. This part belongs to the
    # request transaction: it only happens on the success path.
    active.consumed_at = now
    user.mobile_verified = True
    user.mobile_verified_at = datetime.now(UTC)

    # FR-003: activate the organization on first owner verification.
    organization_status: str | None = None
    if organization is not None:
        organization_status = _status_value(organization.status)
        if organization_status == OrganizationStatus.PENDING_OWNER_REGISTRATION.value:
            organization.status = OrganizationStatus.ACTIVE
            organization_status = _status_value(organization.status)
            await record_audit(
                session,
                "organization.activated",
                organization_id=organization.id,
                entity_type="organization",
                entity_id=organization.id,
            )

    await record_audit(
        session,
        "otp.verified",
        actor_user_id=user.id,
        entity_type="otp_verification",
        entity_id=active.id,
    )
    return {"organization_status": organization_status}
