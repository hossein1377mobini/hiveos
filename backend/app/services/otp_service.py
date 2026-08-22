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
import math
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit, security
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
        select(OtpCode.created_at)
        .where(
            OtpCode.phone == canonical,
            OtpCode.used.is_(False),
            OtpCode.expires_at > now,
            OtpCode.created_at >= now - timedelta(seconds=_COOLDOWN_SECONDS),
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    created = recent.scalar_one_or_none()
    if created is not None:
        # S1-19: report the remaining cooldown in the 429 body so the frontend
        # keeps its resend button disabled for the full window (no 429 loop).
        remaining = (created + timedelta(seconds=_COOLDOWN_SECONDS) - now).total_seconds()
        resend_after = max(1, math.ceil(remaining))
        raise RateLimitedError(
            "please wait before requesting another code",
            resend_after_seconds=resend_after,
        )


async def _issue(session: AsyncSession, owner: Owner, *, void_existing: bool) -> OtpSendResponse:
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


async def verify_otp(
    session: AsyncSession, phone: str, code: str, ip: str | None = None
) -> OtpVerifyResponse:
    canonical = _normalize_phone(phone)
    ip = ip or "unknown"
    now = datetime.now(UTC)
    settings = get_settings()
    lockout_threshold = settings.otp_lockout_max_attempts
    lockout_window = settings.otp_lockout_window_seconds

    # S1-12: account/IP lockout checked BEFORE any per-code logic. It is
    # independent of the per-code ``otp_max_attempts`` cap so that brute-force
    # across resends (which mint a fresh code and thus a fresh per-code budget)
    # still locks the account out.
    locked, retry_after = await ratelimit.otp_lockout_status(canonical, ip, lockout_threshold)
    if locked:
        raise RateLimitedError(
            "too many verification attempts; account locked",
            retry_after=retry_after,
        )

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

    max_attempts = settings.otp_max_attempts
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

        # S1-12: every wrong attempt also counts toward the account/IP lockout
        # (spans codes). Handled ahead of the per-code 429 so an account that
        # crossed the lockout threshold is reported as locked, not just
        # capped on this single code.
        over, lock_retry_after = await ratelimit.otp_lockout_record(
            canonical, ip, lockout_threshold, lockout_window
        )
        if over:
            raise RateLimitedError(
                "too many verification attempts; account locked",
                retry_after=lock_retry_after,
            )

        if new_attempts >= max_attempts:
            raise RateLimitedError("too many failed attempts")
        raise ApiError("invalid verification code")

    # Atomically claim the code (conditional UPDATE). Only ONE concurrent
    # verify can flip used=False -> True, so the "used" replay race is closed
    # even under parallel requests; the loser gets 410 instead of a double
    # activation.
    claimed = await session.execute(
        update(OtpCode)
        .where(
            OtpCode.id == otp.id,
            OtpCode.used.is_(False),
            OtpCode.expires_at > now,
        )
        .values(used=True)
        .returning(OtpCode.id)
    )
    if claimed.scalar_one_or_none() is None:
        raise GoneError("otp expired or already used")

    # S1-12: a successful verification clears the account/IP lockout counters.
    await ratelimit.otp_lockout_clear(canonical, ip)

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
    await session.commit()

    return OtpVerifyResponse(verified=True, userStatus="active", organizationStatus="active")
