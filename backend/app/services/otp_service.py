"""US-003 OTP service: send / resend / verify one-time codes.

Single mock SMS path (ADR-019 decision 4): the ``ISmsProvider`` seam in
``app.services.sms`` is the only touchpoint to the outside world, so swapping in
Kavenegar later is a one-class change. We store only a keyed HMAC (server-secret
pepper) of the 6-digit code — never the code itself — and never write codes to
logs.

Behaviour:
- send_otp / resend_otp resolve the still-``pending`` Owner by canonical phone
  (404 if absent), enforce a 60s resend cooldown (429), persist a fresh OtpCode,
  then hand off to the SMS provider (503 on gateway/offline).
- verify_otp validates against the latest unused, unexpired code (410 if gone),
  caps brute-force at otp_max_attempts (429), records failed attempts (400 on a
  wrong code), and on success activates both Owner and Organization.
"""

import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.config import get_settings
from app.errors import ApiError, GoneError, NotFoundError, RateLimitedError
from app.models import Organization, OtpCode, Owner
from app.schemas import OtpSendResponse, OtpVerifyResponse
from app.services import sms

_COOLDOWN_SECONDS = 60

# ASCII digits only — Persian/Arabic digits are rejected (PO rule).
_PHONE_RE = re.compile(r"^\+[0-9]+$")


def _normalize_phone(phone: str) -> str:
    """Canonicalize to +98xxxxxxxxxx; reject anything non-Iranian with 400."""
    if not phone or not _PHONE_RE.fullmatch(phone):
        raise ApiError("phone must be a canonical +98 Iranian mobile number")
    digits = phone[1:]
    if digits.startswith("0098"):
        digits = digits[2:]
    if digits.startswith("98"):
        national = digits[2:]
        if len(national) == 10 and national.startswith("9"):
            return f"+{digits}"
    raise ApiError("phone must be a canonical +98 Iranian mobile number")


def _generate_code() -> str:
    """Cryptographically secure 6-digit code (000000..999999)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_code(code: str) -> str:
    """Keyed-HMAC of the code with the server secret (pepper), not a plain hash.

    F-3: a DB leak alone cannot reveal codes (requires the server secret), which
    meaningfully shrinks the brute-force surface of the 1M-code space on top of
    the TTL + max-attempts controls.
    """
    return security.otp_hmac(code)


async def _pending_owner(session: AsyncSession, canonical: str) -> Owner:
    result = await session.execute(select(Owner).where(Owner.phone == canonical))
    owner = result.scalar_one_or_none()
    if owner is None or owner.status != "pending":
        raise NotFoundError("no pending owner for this phone")
    return owner


async def _enforce_cooldown(session: AsyncSession, canonical: str) -> None:
    now = datetime.now(UTC)
    recent = await session.execute(
        select(OtpCode.id).where(
            OtpCode.phone == canonical,
            OtpCode.used.is_(False),
            OtpCode.expires_at > now,
            OtpCode.created_at >= now - timedelta(seconds=_COOLDOWN_SECONDS),
        )
    )
    if recent.scalar_one_or_none() is not None:
        raise RateLimitedError("please wait before requesting another code")


async def _issue(
    session: AsyncSession, owner: Owner, *, void_existing: bool
) -> OtpSendResponse:
    canonical = owner.phone
    await _enforce_cooldown(session, canonical)

    if void_existing:
        now = datetime.now(UTC)
        stale = await session.execute(
            select(OtpCode).where(
                OtpCode.phone == canonical,
                OtpCode.used.is_(False),
                OtpCode.expires_at > now,
            )
        )
        for row in stale.scalars():
            row.used = True

    code = _generate_code()
    settings = get_settings()
    otp = OtpCode(
        phone=canonical,
        tenant_id=owner.tenant_id,
        organization_id=owner.organization_id,
        owner_id=owner.id,
        code_hash=_hash_code(code),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.otp_ttl_seconds),
        attempts=0,
        used=False,
    )
    session.add(otp)
    await session.flush()

    # Deliver last so a gateway failure rolls back the persisted code.
    try:
        await sms.get_sms_provider().send(canonical, code)
    except Exception:
        await session.rollback()
        raise

    await session.commit()
    return OtpSendResponse(
        status="sent",
        resendAfterSeconds=_COOLDOWN_SECONDS,
        expiresInSeconds=settings.otp_ttl_seconds,
    )


async def send_otp(session: AsyncSession, phone: str) -> OtpSendResponse:
    canonical = _normalize_phone(phone)
    owner = await _pending_owner(session, canonical)
    return await _issue(session, owner, void_existing=False)


async def resend_otp(session: AsyncSession, phone: str) -> OtpSendResponse:
    canonical = _normalize_phone(phone)
    owner = await _pending_owner(session, canonical)
    return await _issue(session, owner, void_existing=True)


async def verify_otp(session: AsyncSession, phone: str, code: str) -> OtpVerifyResponse:
    canonical = _normalize_phone(phone)
    now = datetime.now(UTC)

    result = await session.execute(
        select(OtpCode)
        .where(
            OtpCode.phone == canonical,
            OtpCode.used.is_(False),
            OtpCode.expires_at > now,
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    otp = result.scalar_one_or_none()
    if otp is None:
        raise GoneError("otp expired or not found")

    max_attempts = get_settings().otp_max_attempts
    if otp.attempts >= max_attempts:
        raise RateLimitedError("too many failed attempts")

    if not hmac.compare_digest(_hash_code(code), otp.code_hash):
        # F-6: atomic increment (no read-modify-write race across concurrent
        # attempts) so brute-forcing cannot slip past the cap.
        result = await session.execute(
            update(OtpCode)
            .where(OtpCode.id == otp.id)
            .values(attempts=OtpCode.attempts + 1)
            .returning(OtpCode.attempts)
        )
        new_attempts = result.scalar_one()
        await session.commit()
        if new_attempts >= max_attempts:
            raise RateLimitedError("too many failed attempts")
        raise ApiError("invalid verification code")

    owner = await session.get(Owner, otp.owner_id) if otp.owner_id else None
    if owner is None:
        owner = (
            await session.execute(select(Owner).where(Owner.phone == canonical))
        ).scalar_one_or_none()
    if owner is None:
        raise NotFoundError("owner not found")

    organization = await session.get(Organization, otp.organization_id)

    owner.status = "active"
    if organization is not None:
        organization.status = "active"
    otp.used = True
    await session.commit()

    return OtpVerifyResponse(verified=True, userStatus="active", organizationStatus="active")
