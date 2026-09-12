"""US-003 (T-S1-4) acceptance tests: verify-otp, lockout, activation, sliding session."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from backend.sms import MockSmsProvider
from tests.test_organization_api import _bootstrap_org, _register_owner
from tests.test_otp_api import fast_otp  # noqa: F401 (pytest fixture used by name)

AUTH = "/api/v1/auth"

_ctx: dict = {}


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap_with_otp(client) -> str:
    """Org + owner + sent OTP; returns bearer token. Code is in MockSmsProvider.SENT."""
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id)
    body = response.json()["data"]
    token = body["session"]["token"]
    engine = _sync_engine()
    with engine.connect() as conn:
        _ctx["mobile"] = conn.execute(
            text("SELECT mobile FROM hiveos.users WHERE id = :id"), {"id": body["user_id"]}
        ).scalar_one()
    engine.dispose()
    _ctx["user_id"] = str(body["user_id"])
    _ctx["org_id"] = str(org_id)
    send = client.post(f"{AUTH}/send-otp", headers=_headers(token))
    assert send.status_code == 200
    return token


def _last_code() -> str:
    return MockSmsProvider.SENT[_ctx["mobile"]][-1]


def test_verify_correct_code_activates_owner_and_org(client):
    token = _bootstrap_with_otp(client)
    response = client.post(f"{AUTH}/verify-otp", json={"code": _last_code()}, headers=_headers(token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["organization_status"] == "active"
    assert data["session"]["token"] == token

    engine = _sync_engine()
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT mobile_verified, mobile_verified_at FROM hiveos.users WHERE id = :id"),
            {"id": _ctx["user_id"]},
        ).one()
        org_status = conn.execute(
            text("SELECT status FROM hiveos.organizations WHERE id = :id"), {"id": _ctx["org_id"]}
        ).scalar_one()
        consumed = conn.execute(
            text("SELECT consumed_at FROM hiveos.otp_verifications WHERE consumed_at IS NOT NULL")
        ).scalar_one()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event IN"
                " ('otp.verified', 'organization.activated')"
            )
        ).scalars().all()
    engine.dispose()

    assert user.mobile_verified is True and user.mobile_verified_at is not None
    assert org_status == "active"
    assert consumed is not None
    assert set(events) == {"otp.verified", "organization.activated"}


def test_verify_accepts_persian_digits(client):
    token = _bootstrap_with_otp(client)
    persian = _last_code().translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    response = client.post(f"{AUTH}/verify-otp", json={"code": persian}, headers=_headers(token))
    assert response.status_code == 200


def test_verify_wrong_code_counts_attempts_and_keeps_state(client):
    token = _bootstrap_with_otp(client)
    response = client.post(f"{AUTH}/verify-otp", json={"code": "0001"}, headers=_headers(token))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OTP_INVALID"
    assert "Remaining attempts: 4" in response.json()["error"]["message"]

    engine = _sync_engine()
    with engine.connect() as conn:
        attempts = conn.execute(text("SELECT failed_attempts FROM hiveos.otp_verifications")).scalar_one()
        org_status = conn.execute(
            text("SELECT status FROM hiveos.organizations WHERE id = :id"), {"id": _ctx["org_id"]}
        ).scalar_one()
        verified = conn.execute(
            text("SELECT mobile_verified FROM hiveos.users WHERE id = :id"), {"id": _ctx["user_id"]}
        ).scalar_one()
    engine.dispose()
    assert attempts == 1
    assert org_status == "pending_owner_registration"  # FR-004: no state change
    assert verified is False


def test_verify_locks_after_max_attempts(client):
    token = _bootstrap_with_otp(client)
    statuses = []
    for _ in range(5):
        response = client.post(f"{AUTH}/verify-otp", json={"code": "0001"}, headers=_headers(token))
        body = response.json()
        statuses.append((response.status_code, body.get("error", {}).get("code"), body.get("error", {}).get("message")))
    assert response.status_code == 429, f"statuses={statuses}"
    assert response.json()["error"]["code"] == "OTP_LOCKED"

    # scenario 4: locked for the same number - even send/resend are blocked
    send = client.post(f"{AUTH}/send-otp", headers=_headers(token))
    assert send.status_code == 429
    assert send.json()["error"]["code"] == "OTP_LOCKED"

    engine = _sync_engine()
    with engine.connect() as conn:
        locked_until, attempts = conn.execute(
            text("SELECT locked_until, failed_attempts FROM hiveos.otp_verifications")
        ).one()
        locked_events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'otp.locked'")
        ).scalar_one()
    engine.dispose()
    assert locked_until is not None and locked_until > datetime.now(UTC)
    assert attempts == 5
    assert locked_events == 1


def test_verify_expired_code_rejected_then_resend_works(client, fast_otp):  # noqa: F811 (fixture reuse)
    token = _bootstrap_with_otp(client)
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE hiveos.otp_verifications SET expires_at = now() - interval '1 minute'"))
    engine.dispose()
    response = client.post(f"{AUTH}/verify-otp", json={"code": "1234"}, headers=_headers(token))
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "OTP_EXPIRED"

    # FR-005: resend after expiry (cooldown zeroed by fixture), then verify the new code
    resend = client.post(f"{AUTH}/resend-otp", headers=_headers(token))
    assert resend.status_code == 200
    verify = client.post(f"{AUTH}/verify-otp", json={"code": _last_code()}, headers=_headers(token))
    assert verify.status_code == 200


def test_verify_without_active_code_404(client):
    token = _bootstrap_with_otp(client)
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE hiveos.otp_verifications SET consumed_at = now()"))
    engine.dispose()
    response = client.post(f"{AUTH}/verify-otp", json={"code": "1234"}, headers=_headers(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "OTP_NOT_FOUND"


def test_verify_replays_consumed_code_409(client):
    token = _bootstrap_with_otp(client)
    code = _last_code()
    first = client.post(f"{AUTH}/verify-otp", json={"code": code}, headers=_headers(token))
    assert first.status_code == 200
    replay = client.post(f"{AUTH}/verify-otp", json={"code": code}, headers=_headers(token))
    assert replay.status_code == 409  # already-verified guard fires first (FR-006 no replay)
    assert replay.json()["error"]["code"] == "MOBILE_ALREADY_VERIFIED"


def test_session_slides_on_authenticated_request(client):
    token = _bootstrap_with_otp(client)
    before = datetime.now(UTC)
    client.post(f"{AUTH}/send-otp", headers=_headers(token))  # any authenticated request
    engine = _sync_engine()
    with engine.connect() as conn:
        expires_at = conn.execute(text("SELECT expires_at FROM hiveos.sessions")).scalar_one()
    engine.dispose()
    ttl = timedelta(days=get_settings().session_ttl_days)
    assert expires_at - before > ttl - timedelta(minutes=5)  # slid to a fresh 7 days


def test_verify_validation_error_on_bad_body(client):
    token = _bootstrap_with_otp(client)
    response = client.post(f"{AUTH}/verify-otp", json={"code": "12"}, headers=_headers(token))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
