"""US-003 (T-S1-3) acceptance tests: OTP send/resend service + endpoints."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from backend.organization.otp_service import PURPOSE_OWNER_VERIFICATION, code_digest
from backend.sms import MockSmsProvider, SmsDeliveryError
from tests.test_organization_api import _bootstrap_org, _register_owner

AUTH = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _clean_mock_sms():
    MockSmsProvider.SENT.clear()
    yield
    MockSmsProvider.SENT.clear()


@pytest.fixture()
def fast_otp(monkeypatch):
    """Zero resend cooldown so tests can send multiple codes without sleeping."""
    monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "0")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("OTP_RESEND_COOLDOWN_SECONDS")
    get_settings.cache_clear()


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _owner_token(client) -> tuple[str, str]:
    """Bootstrap org + owner; returns (bearer token, owner mobile)."""
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id)
    body = response.json()["data"]
    # OwnerCreated does not echo the mobile; read it from the DB (US-002 keeps
    # the bootstrap response minimal).
    engine = _sync_engine()
    with engine.connect() as conn:
        mobile = conn.execute(
            text("SELECT mobile FROM hiveos.users WHERE id = :id"),
            {"id": body["user_id"]},
        ).scalar_one()
    engine.dispose()
    return body["session"]["token"], mobile


def test_send_otp_requires_auth(client):
    response = client.post(f"{AUTH}/send-otp")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_send_otp_success_creates_row_and_audits(client):
    token, mobile = _owner_token(client)
    before = datetime.now(UTC)
    response = client.post(f"{AUTH}/send-otp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["expires_at"] and data["resend_available_at"]

    engine = _sync_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT mobile, purpose, code_hash, expires_at, consumed_at, failed_attempts"
                " FROM hiveos.otp_verifications"
            )
        ).one()
        event = conn.execute(
            text("SELECT event FROM hiveos.audit_logs WHERE event = 'otp.sent'")
        ).scalar_one()
    engine.dispose()

    assert row.mobile == mobile
    assert row.purpose == PURPOSE_OWNER_VERIFICATION
    assert row.consumed_at is None
    assert row.failed_attempts == 0
    codes = MockSmsProvider.SENT[mobile]
    assert len(codes) == 1 and len(codes[0]) == 6 and codes[0].isdigit()
    # digest binds the user id: recompute from the stored user row
    with engine.connect() as conn:
        user_id = conn.execute(
            text("SELECT id FROM hiveos.users WHERE mobile = :m"), {"m": mobile}
        ).scalar_one()
    engine.dispose()
    assert row.code_hash == code_digest(user_id, codes[0])
    assert event == "otp.sent"
    # expires_at is roughly now + 5 minutes (Amendment 2 TTL)
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    assert timedelta(minutes=4) < expires - before < timedelta(minutes=6)


def test_send_otp_enforces_cooldown(client):
    token, _ = _owner_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"{AUTH}/send-otp", headers=headers)
    assert first.status_code == 200
    second = client.post(f"{AUTH}/send-otp", headers=headers)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "OTP_COOLDOWN"


def test_resend_invalidates_previous_code(client, fast_otp):
    token, mobile = _owner_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"{AUTH}/send-otp", headers=headers)
    assert first.status_code == 200
    second = client.post(f"{AUTH}/resend-otp", headers=headers)
    assert second.status_code == 200
    assert len(MockSmsProvider.SENT[mobile]) == 2

    engine = _sync_engine()
    with engine.connect() as conn:
        active = conn.execute(
            text(
                "SELECT code_hash FROM hiveos.otp_verifications WHERE consumed_at IS NULL"
            )
        ).fetchall()
        total = conn.execute(text("SELECT count(*) FROM hiveos.otp_verifications")).scalar_one()
        resent = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'otp.resent'")
        ).scalar_one()
    engine.dispose()

    # previous code consumed (row kept, consumed_at set); exactly one active remains
    assert total == 2 and len(active) == 1
    assert active[0][0] == code_digest(_user_id(mobile), MockSmsProvider.SENT[mobile][1])
    assert resent == 1


def _user_id(mobile: str):
    engine = _sync_engine()
    with engine.connect() as conn:
        user_id = conn.execute(
            text("SELECT id FROM hiveos.users WHERE mobile = :m"), {"m": mobile}
        ).scalar_one()
    engine.dispose()
    return user_id


def test_send_otp_delivery_failure_persists_event(client, monkeypatch):
    token, mobile = _owner_token(client)

    def _failing_provider():
        class _Broken:
            async def send_otp(self, mobile: str, code: str) -> None:
                raise SmsDeliveryError("gateway unreachable")

        return _Broken()

    monkeypatch.setattr("backend.organization.otp_service.get_sms_provider", _failing_provider)
    response = client.post(f"{AUTH}/send-otp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SMS_DELIVERY_FAILED"
    # scenario 5: event survives the failed request (own transaction)
    engine = _sync_engine()
    with engine.connect() as conn:
        failed_events = conn.execute(
            text(
                "SELECT count(*) FROM hiveos.audit_logs WHERE event = 'otp.delivery_failed'"
            )
        ).scalar_one()
        otp_rows = conn.execute(text("SELECT count(*) FROM hiveos.otp_verifications")).scalar_one()
    engine.dispose()
    assert failed_events == 1
    assert otp_rows == 0  # nothing persisted from the failed request


def test_send_otp_rejects_already_verified_user(client):
    token, mobile = _owner_token(client)
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE hiveos.users SET mobile_verified = true WHERE mobile = :m"),
            {"m": mobile},
        )
    engine.dispose()
    response = client.post(f"{AUTH}/send-otp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MOBILE_ALREADY_VERIFIED"


def test_code_digest_binds_user_id():
    assert code_digest("u1", "123456") != code_digest("u2", "123456")
