"""Redis-backed rate limiting + OTP lockout primitives (S1-12).

Two independent concerns, both fixed-window counters in Redis:

1. **IP rate limiting** on the unauthenticated registration endpoints
   (``/organizations``, ``/users/owner``) and the OTP send/resend endpoints.
   These paths do PBKDF2-600k hashing and/or emit SMS, so an unauthenticated
   caller hammering them is a CPU/DoS and SMS-cost vector. There is no account
   identity yet, so the key is the client IP.

2. **OTP verify lockout** keyed independently by account (canonical phone) and
   by client IP. The existing per-code ``otp_max_attempts`` cap only protects a
   *single* code; an attacker who triggers a resend gets a fresh code and thus a
   fresh per-code budget. This lockout spans codes so brute-forcing across
   resends still gets shut down.

Design notes

- **Fixed window**: ``INCR`` (atomic) + conditional ``EXPIRE`` so the counter
  self-expires after the window; no sweeper needed. Only the request that
  creates the key (the ``INCR`` returning 1) sets the TTL.
- **Fail open**: a Redis outage degrades to "allow" rather than hard-downing
  onboarding. Rate limiting is a DoS *mitigation*, not a correctness
  dependency, so the app must keep working if the counter store is briefly
  unavailable. Failures are logged, never swallowed silently (S1-20 posture).
- **No PII in keys**: keys are the client IP and the canonical phone string;
  both TTL out within the window. Nothing secret is stored.

``get_redis`` is a lazy module-level singleton bound to the running event loop
on first command; it is safe to call from within the FastAPI request cycle.
"""

import contextlib
import logging

from redis import asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

# Singleton async client, created lazily on first use (inside a running loop).
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def _reset_client_for_tests() -> None:
    """Close + drop the cached client (test seams only)."""
    global _client
    _client = None


# --------------------------------------------------------------------------- #
# Fixed-window counter core
# --------------------------------------------------------------------------- #
async def _increment_with_ttl(key: str, window_seconds: int) -> int:
    """Atomically INCRease ``key`` and ensure it expires after the window.

    Returns the new count. ``INCR`` is atomic, so exactly one concurrent caller
    observes ``1`` and is responsible for setting the expiry.
    """
    r = get_redis()
    count = await r.incr(key)
    if count == 1:  # only the key-creator sets the TTL
        await r.expire(key, window_seconds)
    return count


async def _remaining_ttl(*keys: str) -> int:
    """Max remaining TTL (seconds) across keys; 1 as a floor."""
    r = get_redis()
    ttl = 1
    for key in keys:
        with contextlib.suppress(Exception):
            ttl = max(ttl, await r.ttl(key))
    return max(ttl, 1)


# --------------------------------------------------------------------------- #
# IP rate limiting (registration + OTP send)
# --------------------------------------------------------------------------- #
async def enforce_ip_limit(
    *,
    ip: str,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Raise ``RateLimitedError`` if ``ip`` has exceeded ``limit`` in the window.

    Fails open: when Redis is unavailable the request is allowed through and a
    warning is logged rather than blocking onboarding on an infra hiccup.
    """
    if not get_settings().rate_limit_enabled:
        return

    key = f"rl:{bucket}:{ip}"
    try:
        count = await _increment_with_ttl(key, window_seconds)
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning(
            "rate-limit store unavailable for %s (failing open): %s", bucket, exc
        )
        return

    if count > limit:
        from app.errors import RateLimitedError  # local import: avoid cycle at boot

        raise RateLimitedError(
            f"too many requests (limit {limit} per {window_seconds}s)",
            retry_after=await _remaining_ttl(key),
        )


# --------------------------------------------------------------------------- #
# OTP verify lockout (account + IP, independent of per-code max attempts)
# --------------------------------------------------------------------------- #
def _otp_keys(account: str, ip: str) -> list[str]:
    return [f"otp:fail:acct:{account}", f"otp:fail:ip:{ip}"]


async def otp_lockout_status(account: str, ip: str, threshold: int) -> tuple[bool, int]:
    """(is_locked, retry_after) — locked when either counter reaches threshold."""
    if not get_settings().rate_limit_enabled:
        return False, 1

    keys = _otp_keys(account, ip)
    try:
        r = get_redis()
        counts = [int(c or 0) for c in await r.mget(keys)]
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning("otp lockout store unavailable (failing open): %s", exc)
        return False, 1

    if max(counts, default=0) >= threshold:
        return True, await _remaining_ttl(*keys)
    return False, 1


async def otp_lockout_record(
    account: str, ip: str, threshold: int, window_seconds: int
) -> tuple[bool, int]:
    """Increment both failure counters; (now_locked, retry_after)."""
    if not get_settings().rate_limit_enabled:
        return False, 1

    keys = _otp_keys(account, ip)
    try:
        counts = [await _increment_with_ttl(k, window_seconds) for k in keys]
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning("otp lockout store unavailable (failing open): %s", exc)
        return False, 1

    if max(counts, default=0) >= threshold:
        return True, await _remaining_ttl(*keys)
    return False, 1


async def otp_lockout_clear(account: str, ip: str) -> None:
    """Reset both counters on a successful verification."""
    if not get_settings().rate_limit_enabled:
        return
    keys = _otp_keys(account, ip)
    try:
        await get_redis().delete(*keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("otp lockout clear unavailable: %s", exc)
