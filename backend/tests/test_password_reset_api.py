"""US-010 (T-S1-6) acceptance tests: password reset via OTP-SMS."""

import pytest
from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from backend.sms import MockSmsProvider
from tests.test_otp_api import _owner_token
from tests.test_otp_api import fast_otp as fast_otp  # noqa: F401,F811

AUTH = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _clean_mock_sms():
    MockSmsProvider.SENT.clear()
    yield
    MockSmsProvider.SENT.clear()


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _last_code(mobile: str) -> str:
    codes = MockSmsProvider.SENT.get(mobile, [])
    assert codes, f"no SMS recorded for {mobile}"
    return codes[-1]


def _request_reset(client, mobile: str):
    response = client.post(f"{AUTH}/password/reset-request", json={"mobile": mobile})
    assert response.status_code == 200, response.text  # surface 429 codes on flakes
    return response


def _reset_password(client, mobile: str, code: str, new_password="N3w!Secret"):
    return client.post(
        f"{AUTH}/password/reset",
        json={
            "mobile": mobile,
            "code": code,
            "new_password": new_password,
            "confirm_password": new_password,
        },
    )


def test_full_reset_flow_revokes_sessions_and_swaps_password(client):
    token, mobile = _owner_token(client)
    assert _request_reset(client, mobile).status_code == 200
    code = _last_code(mobile)

    assert (
        client.post(f"{AUTH}/password/reset-verify", json={"mobile": mobile, "code": code}).status_code
        == 200
    )
    response = _reset_password(client, mobile, code)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["password_reset"] is True and data["sessions_revoked"] == 1

    engine = _sync_engine()
    with engine.connect() as conn:
        otp = conn.execute(
            text(
                "SELECT consumed_at FROM hiveos.otp_verifications WHERE purpose = 'password_reset'"
            )
        ).scalar_one()
        sessions = conn.execute(
            text("SELECT count(*) FROM hiveos.sessions WHERE revoked_at IS NULL")
        ).scalar_one()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event IN ("
                "'password.reset.requested', 'otp.sent', 'otp.verified',"
                "'password.reset.completed')"
            )
        ).scalars().all()
    engine.dispose()

    assert otp is not None  # consumed (FR-004)
    assert sessions == 0  # every active session revoked
    assert set(events) == {
        "password.reset.requested",
        "otp.sent",
        "otp.verified",
        "password.reset.completed",
    }

    # FR-004: the old session is dead -> 401 SESSION_REVOKED
    old = client.post(f"{AUTH}/send-otp", headers={"Authorization": f"Bearer {token}"})
    assert old.status_code == 401
    assert old.json()["error"]["code"] == "SESSION_REVOKED"

    # US-009 login with the NEW password works, the OLD one fails
    assert (
        client.post(f"{AUTH}/login", json={"username": "owner.one", "password": "N3w!Secret"}).status_code
        == 200
    )
    old_login = client.post(f"{AUTH}/login", json={"username": "owner.one", "password": "Str0ng!Pass"})
    assert old_login.status_code == 401


def test_reset_request_unknown_mobile_is_generic_and_silent(client):
    _owner_token(client)  # an account exists but with another mobile
    response = _request_reset(client, "+989120000000")
    assert response.status_code == 200
    body = response.json()["data"]
    assert "message" in body  # same shape as the known-mobile response

    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT count(*) FROM hiveos.otp_verifications WHERE purpose = 'password_reset'")
        ).scalar_one()
        events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'password.reset.requested'")
        ).scalar_one()
    engine.dispose()
    assert rows == 0  # no OTP was created
    assert events == 0  # nothing user-specific to audit
    assert "+989120000000" not in MockSmsProvider.SENT  # no SMS sent


def test_reset_verify_unknown_mobile_no_disclosure(client):
    response = client.post(
        f"{AUTH}/password/reset-verify", json={"mobile": "+989120000000", "code": "1234"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OTP_INVALID"
    # no per-account counter in the message (that would leak existence)
    assert "Remaining attempts" not in response.json()["error"]["message"]


def test_reset_wrong_code_counts_attempts_and_locks(client):
    _, mobile = _owner_token(client)
    assert _request_reset(client, mobile).status_code == 200
    for _ in range(5):
        response = client.post(
            f"{AUTH}/password/reset-verify", json={"mobile": mobile, "code": "0000"}
        )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "OTP_LOCKED"

    engine = _sync_engine()
    with engine.connect() as conn:
        attempts, locked_until = conn.execute(
            text(
                "SELECT failed_attempts, locked_until FROM hiveos.otp_verifications"
                " WHERE purpose = 'password_reset'"
            )
        ).one()
        failed_events = conn.execute(
            text(
                "SELECT count(*) FROM hiveos.audit_logs WHERE event IN ('otp.failed','otp.locked')"
            )
        ).scalar_one()
    engine.dispose()
    assert attempts == 5 and locked_until is not None and failed_events == 5


def test_reset_expired_code_rejected_and_resend_possible(client, fast_otp):
    _, mobile = _owner_token(client)
    assert _request_reset(client, mobile).status_code == 200
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE hiveos.otp_verifications SET expires_at = now() - interval '1 minute'"
                " WHERE purpose = 'password_reset'"
            )
        )
    engine.dispose()

    response = client.post(
        f"{AUTH}/password/reset-verify", json={"mobile": mobile, "code": _last_code(mobile)}
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "OTP_EXPIRED"

    # scenario 2: resend after expiry works (cooldown zeroed by fast_otp)
    assert _request_reset(client, mobile).status_code == 200
    new_code = _last_code(mobile)
    assert (
        client.post(f"{AUTH}/password/reset-verify", json={"mobile": mobile, "code": new_code}).status_code
        == 200
    )


def test_reset_rejects_policy_violation_and_keeps_otp(client):
    _, mobile = _owner_token(client)
    assert _request_reset(client, mobile).status_code == 200
    code = _last_code(mobile)

    response = _reset_password(client, mobile, code, new_password="weak")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_POLICY"

    engine = _sync_engine()
    with engine.connect() as conn:
        consumed = conn.execute(
            text("SELECT consumed_at FROM hiveos.otp_verifications WHERE purpose='password_reset'")
        ).scalar_one()
        events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'password.reset.completed'")
        ).scalar_one()
    engine.dispose()
    assert consumed is None  # the code is NOT burned by a policy failure
    assert events == 0


def test_reset_rejects_password_mismatch(client):
    _, mobile = _owner_token(client)
    assert _request_reset(client, mobile).status_code == 200
    code = _last_code(mobile)
    response = client.post(
        f"{AUTH}/password/reset",
        json={
            "mobile": mobile,
            "code": code,
            "new_password": "N3w!Secret",
            "confirm_password": "N3w!Other",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_MISMATCH"


def test_resend_invalidates_previous_reset_code(client, fast_otp):
    _, mobile = _owner_token(client)
    assert _request_reset(client, mobile).status_code == 200
    first_code = _last_code(mobile)
    assert _request_reset(client, mobile).status_code == 200
    second_code = _last_code(mobile)
    assert first_code != second_code

    stale = client.post(f"{AUTH}/password/reset-verify", json={"mobile": mobile, "code": first_code})
    assert stale.status_code == 400  # invalidated by the resend (one active per purpose)
    fresh = client.post(f"{AUTH}/password/reset-verify", json={"mobile": mobile, "code": second_code})
    assert fresh.status_code == 200
