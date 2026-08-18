"""SMS delivery seam (ADR-019 decision 4): mock first, Kavenegar later.

``ISmsProvider`` is the only contract the OTP service depends on, so a real
Kavenegar provider is a drop-in: implement ``ISmsProvider`` (an HTTP call to
Kavenegar's send API) and return it from ``get_sms_provider()`` — no change to
``otp_service`` is required.

The mock prints the code in DEV ONLY so the onboarding flow can be exercised
end-to-end without a gateway. This is the single, clearly-marked place a code is
ever surfaced; a production provider must never log it. ``mock_otp_offline``
simulates FR-007 (no internet / gateway down) by raising 503.
"""

from typing import Protocol

from app.config import get_settings
from app.errors import GatewayUnavailableError


class ISmsProvider(Protocol):
    async def send(self, phone: str, code: str) -> None:
        """Deliver a one-time code to ``phone``.

        Raise ``GatewayUnavailableError`` when the gateway/internet is unreachable.
        """
        ...


class MockOtpProvider:
    """DEV-ONLY provider: prints the code; honours the offline simulation flag."""

    async def send(self, phone: str, code: str) -> None:
        if get_settings().mock_otp_offline:
            raise GatewayUnavailableError("sms gateway unreachable (offline simulation)")
        # DEV ONLY — a real provider must never log the code.
        print(f"[MOCK-SMS] (developers only) OTP for {phone}: {code}")


def get_sms_provider() -> ISmsProvider:
    """Factory. Swap in ``KavenegarOtpProvider`` here when the gateway goes live."""
    return MockOtpProvider()
