"""US-003 SMS seam — MockOtpProvider honours the FR-007 offline simulation."""

import pytest

from app.config import get_settings
from app.errors import GatewayUnavailableError
from app.services.sms import MockOtpProvider


async def test_offline_provider_raises_gateway_unavailable(monkeypatch):
    monkeypatch.setattr(get_settings(), "mock_otp_offline", True)
    with pytest.raises(GatewayUnavailableError):
        await MockOtpProvider().send("+989100222000", "123456")


async def test_online_provider_delivers_without_error(monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "mock_otp_offline", False)
    await MockOtpProvider().send("+989100222000", "123456")  # must not raise
    out = capsys.readouterr().out
    assert "MOCK-SMS" in out and "123456" in out
