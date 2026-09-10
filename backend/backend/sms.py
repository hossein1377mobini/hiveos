"""SMS provider abstraction (US-003).

- mock: dev/test provider; keeps the code in memory so the test suite can
  read it, and logs it. Never used with real subscriber numbers.
- melipayamak: real gateway (rest.payamak-panel.com). Credentials come from
  environment (ADR-022: no secrets in git; the PO enters service keys via the
  admin panel US-1601/1605 later - until then staging runs on 'mock').

Failures raise SmsDeliveryError so the API can answer with the explicit
'server needs internet access' error of US-003 FR-007 / scenario 5.
"""

import logging
from typing import Protocol

import httpx

from backend.config import get_settings

logger = logging.getLogger("hiveos.sms")


class SmsDeliveryError(Exception):
    """The SMS gateway could not be reached or refused the message."""


class SmsProvider(Protocol):
    async def send_otp(self, mobile: str, code: str) -> None: ...


class MockSmsProvider:
    """Dev/test provider: records codes in memory, logs them."""

    SENT: dict[str, list[str]] = {}

    async def send_otp(self, mobile: str, code: str) -> None:
        MockSmsProvider.SENT.setdefault(mobile, []).append(code)
        logger.info("[mock-sms] OTP for %s -> %s (dev only, never in production)", mobile, code)


class MelipayamakSmsProvider:
    """Melipayamak REST gateway (US-003 FR-001)."""

    SEND_URL = "https://rest.payamak-panel.com/api/SendSMS/SendSMS"

    async def send_otp(self, mobile: str, code: str) -> None:
        settings = get_settings()
        payload = {
            "username": settings.melipayamak_username,
            "password": settings.melipayamak_password,
            "to": mobile,
            "from": settings.melipayamak_sender,
            # Message text must stay Persian per terminology (terminology section 7).
            "text": f"HiveOS\nکد تأیید شما: {code}",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.SEND_URL, data=payload)
        except httpx.HTTPError as exc:
            raise SmsDeliveryError("SMS gateway unreachable") from exc
        if response.status_code != 200:
            raise SmsDeliveryError(f"SMS gateway refused message (HTTP {response.status_code})")
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        # Melipayamak returns {"Value": "...", "RetStatus": 1, "StrRetStatus": "Ok"}
        if str(body.get("RetStatus", "")) not in {"1", "Ok"}:
            raise SmsDeliveryError(f"SMS gateway error: {body.get('StrRetStatus', 'unknown')}")


def get_sms_provider() -> SmsProvider:
    settings = get_settings()
    if settings.sms_provider == "melipayamak":
        return MelipayamakSmsProvider()
    return MockSmsProvider()
