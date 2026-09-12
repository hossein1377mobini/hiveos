"""SMS provider abstraction (US-003).

- mock: dev/test provider; generates a 4-digit code, keeps it in memory so
  the test suite can read it, and logs it. Never used with real subscriber
  numbers (ADR-019).
- melipayamak: the console OTP service (ADR-016 amendment 2026-09-08,
  CHANGE-029): POST https://console.melipayamak.com/api/send/otp/{serviceId}
  with {"to": "09..."}; Melipayamak generates and delivers the 4-digit code
  and returns it in the response body ({"code": "1234", "status": ""}). The
  serviceId acts as the credential. rest.payamak-panel.com (panel REST) is
  NOT used per the infrastructure decision of 2026-09-08.

Failures raise SmsDeliveryError so the API can answer with the explicit
'server needs internet access' error of US-003 FR-007 / scenario 5.
"""

import logging
import secrets
from typing import Protocol

import httpx

from backend.config import get_settings

logger = logging.getLogger("hiveos.sms")


class SmsDeliveryError(Exception):
    """The SMS gateway could not be reached or refused the message."""


class SmsProvider(Protocol):
    """Delivers one OTP and returns the code that was actually sent."""

    async def send_otp(self, mobile: str) -> str: ...


class MockSmsProvider:
    """Dev/test provider: generates a 4-digit code, records it, logs it."""

    SENT: dict[str, list[str]] = {}

    async def send_otp(self, mobile: str) -> str:
        code = f"{secrets.randbelow(10_000):04d}"
        MockSmsProvider.SENT.setdefault(mobile, []).append(code)
        logger.info("[mock-sms] OTP for %s -> %s (dev only, never in production)", mobile, code)
        return code


class MelipayamakSmsProvider:
    """Melipayamak console OTP service (US-003 FR-001, ADR-016 amendment)."""

    async def send_otp(self, mobile: str) -> str:
        settings = get_settings()
        url = f"https://console.melipayamak.com/api/send/otp/{settings.melipayamak_otp_service_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json={"to": mobile})
        except httpx.HTTPError as exc:
            raise SmsDeliveryError("SMS gateway unreachable") from exc
        if response.status_code != 200:
            raise SmsDeliveryError(f"SMS gateway refused message (HTTP {response.status_code})")
        try:
            body = response.json()
        except ValueError:
            body = {}
        # Melipayamak console OTP: {"code": "1234", "status": ""} on success.
        code = str(body.get("code", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            detail = str(body.get("status") or body.get("message") or "unexpected response")
            raise SmsDeliveryError(f"SMS gateway error: {detail}")
        return code


def get_sms_provider() -> SmsProvider:
    settings = get_settings()
    if settings.sms_provider == "melipayamak":
        return MelipayamakSmsProvider()
    return MockSmsProvider()
