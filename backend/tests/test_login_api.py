"""US-009 (T-S1-5) acceptance tests: login, lockout, logout."""


from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_organization_api import _bootstrap_org, _register_owner

AUTH = "/api/v1/auth"


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _credentials(client) -> dict:
    """Bootstrap org + owner; returns login credentials + owner ids."""
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id)
    body = response.json()["data"]
    return {
        "username": "owner.one",
        "password": "Str0ng!Pass",
        "user_id": str(body["user_id"]),
        "organization_id": org_id,
    }


def _login(client, username: str, password: str):
    return client.post(f"{AUTH}/login", json={"username": username, "password": password})


def test_login_success_creates_session_and_resets_counter(client):
    creds = _credentials(client)
    # one failed attempt first so the reset is observable
    _login(client, creds["username"], "Wr0ng!Pass")

    response = _login(client, creds["username"], creds["password"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == creds["user_id"]
    assert data["organization_id"] == creds["organization_id"]
    token = data["session"]["token"]
    assert token and data["session"]["expires_at"]

    engine = _sync_engine()
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT failed_login_count, locked_until FROM hiveos.users WHERE id = :id"),
            {"id": creds["user_id"]},
        ).one()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event IN"
                " ('auth.login.succeeded', 'session.created')"
            )
        ).scalars().all()
        attempts = conn.execute(
            text("SELECT successful FROM hiveos.login_attempts ORDER BY attempted_at")
        ).scalars().all()
    engine.dispose()

    assert user.failed_login_count == 0 and user.locked_until is None
    assert set(events) == {"auth.login.succeeded", "session.created"}
    assert attempts == [False, True]
    # the new token is usable (sliding window applies on activity)
    ok = client.post(f"{AUTH}/send-otp", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_login_wrong_password_generic_error_and_counter(client):
    creds = _credentials(client)
    response = _login(client, creds["username"], "Wr0ng!Pass")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
    # no field disclosure: single generic message, remaining attempts announced
    assert "Remaining attempts: 4" in body["error"]["message"]

    engine = _sync_engine()
    with engine.connect() as conn:
        attempts = conn.execute(text("SELECT failed_login_count FROM hiveos.users")).scalar_one()
    engine.dispose()
    assert attempts == 1


def test_login_unknown_username_same_generic_error(client):
    _credentials(client)  # some account exists
    response = _login(client, "ghost.user", "Whatever!123")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
    # no field disclosure: same code and message shape as wrong password
    assert "Remaining attempts" not in response.json()["error"]["message"]


def test_login_case_insensitive_username(client):
    creds = _credentials(client)
    response = _login(client, "OWNER.ONE", creds["password"])
    assert response.status_code == 200


def test_login_locks_after_five_failures(client):
    creds = _credentials(client)
    for _ in range(5):
        response = _login(client, creds["username"], "Wr0ng!Pass")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"

    engine = _sync_engine()
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT failed_login_count, locked_until FROM hiveos.users WHERE id = :id"),
            {"id": creds["user_id"]},
        ).one()
        locked_events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'auth.account.locked'")
        ).scalar_one()
    engine.dispose()
    assert user.failed_login_count == 5 and user.locked_until is not None
    assert locked_events == 1

    # locked: even the CORRECT password is rejected while the lock is active
    still_locked = _login(client, creds["username"], creds["password"])
    assert still_locked.status_code == 429
    assert still_locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_login_unlocks_and_resets_after_lock_expiry(client):
    creds = _credentials(client)
    for _ in range(5):
        _login(client, creds["username"], "Wr0ng!Pass")
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE hiveos.users SET locked_until = now() - interval '1 minute'"))
    engine.dispose()

    response = _login(client, creds["username"], creds["password"])
    assert response.status_code == 200

    engine = _sync_engine()
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT failed_login_count FROM hiveos.users WHERE id = :id"),
            {"id": creds["user_id"]},
        ).scalar_one()
    engine.dispose()
    assert count == 0  # scenario 3: counter resets after the lock period


def test_logout_revokes_session(client):
    creds = _credentials(client)
    token = _login(client, creds["username"], creds["password"]).json()["data"]["session"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(f"{AUTH}/logout", headers=headers)
    assert response.status_code == 200

    engine = _sync_engine()
    with engine.connect() as conn:
        revoked_count = conn.execute(
            text("SELECT count(*) FROM hiveos.sessions WHERE revoked_at IS NOT NULL")
        ).scalar_one()
        events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'session.expired'")
        ).scalar_one()
    engine.dispose()
    assert revoked_count == 1 and events == 1

    reuse = client.post(f"{AUTH}/send-otp", headers=headers)
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "SESSION_REVOKED"


def test_login_attempt_recorded_for_unknown_username(client):
    _credentials(client)
    _login(client, "ghost.user", "Whatever!123")
    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT user_id, username_attempted, successful FROM hiveos.login_attempts")
        ).all()
    engine.dispose()
    assert rows == [(None, "ghost.user", False)]  # auditable, no account disclosure
