"""US-001/US-002 API acceptance tests (T-S1-2).

Runs against the real dev database: constraint behavior, audit rows and
transactional rollback are part of the acceptance criteria.
"""

import hashlib
import uuid

from sqlalchemy import create_engine, text

from backend.config import get_settings

ORG_BODY = {"name": "شرکت آزمایشی", "industry": "fintech", "size": "10_50"}
OWNER_BODY = {
    "username": "owner.one",
    "mobile": "9121112233",
    "password": "Str0ng!Pass",
    "confirm_password": "Str0ng!Pass",
}


def _sync_engine():
    return create_engine(get_settings().database_url.replace("+asyncpg", "+psycopg"))


def _scalar(client, sql):
    with _sync_engine().connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def _counts(client):
    with _sync_engine().connect() as conn:
        return {
            "orgs": conn.execute(text("SELECT count(*) FROM hiveos.organizations")).scalar_one(),
            "workspaces": conn.execute(text("SELECT count(*) FROM hiveos.workspaces")).scalar_one(),
            "users": conn.execute(text("SELECT count(*) FROM hiveos.users")).scalar_one(),
            "sessions": conn.execute(text("SELECT count(*) FROM hiveos.sessions")).scalar_one(),
            "owner_created_audits": conn.execute(
                text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'owner.created'")
            ).scalar_one(),
        }


def _register_org(client, **overrides):
    return client.post("/api/v1/auth/register-organization", json={**ORG_BODY, **overrides})


def _register_owner(client, organization_id, **overrides):
    body = {**OWNER_BODY, "organization_id": organization_id, **overrides}
    return client.post("/api/v1/auth/owner", json=body)


def _bootstrap_org(client) -> str:
    return _register_org(client).json()["data"]["organization_id"]


# ---------------------------------------------------------------- US-001


def test_register_organization_success_creates_org_workspace_tenant(client):
    response = _register_org(client)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    # FR-004: born pending owner registration.
    assert data["status"] == "pending_owner_registration"
    # FR-003: unique tenant id generated per organization.
    uuid.UUID(data["tenant_id"])
    second = _register_org(client, name="سازمان دوم").json()["data"]
    assert second["tenant_id"] != data["tenant_id"]

    # FR-002: primary workspace created with the organization (US-001 AC scenario 1).
    with _sync_engine().connect() as conn:
        workspaces = conn.execute(
            text("SELECT name, is_primary FROM hiveos.workspaces WHERE organization_id = :id"),
            {"id": data["organization_id"]},
        ).all()
    assert workspaces == [("فضای کاری اصلی", True)]
    # C3: pending expiry window is set on creation.
    with _sync_engine().connect() as conn:
        pending_expires_at = conn.execute(
            text("SELECT pending_expires_at FROM hiveos.organizations WHERE id = :id"),
            {"id": data["organization_id"]},
        ).scalar_one()
    assert pending_expires_at is not None


def test_register_organization_invalid_name_rejected(client):
    response = _register_org(client, name="اب")  # 2 chars < minimum 3 (US-001 validation rules)
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    counts = _counts(client)
    assert (counts["orgs"], counts["workspaces"]) == (0, 0)  # no partial data


def test_register_organization_invalid_size_rejected(client):
    response = _register_org(client, size="1_5")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_organization_audits_created_events(client):
    data = _register_org(client).json()["data"]
    with _sync_engine().connect() as conn:
        events = conn.execute(
            text("SELECT event FROM hiveos.audit_logs WHERE organization_id = :id ORDER BY event"),
            {"id": data["organization_id"]},
        ).scalars().all()
    # US-001 events (tenant.created realized as the unique tenant_id assignment, FR-003).
    assert events == ["organization.created", "tenant.created", "workspace.created"]


# ---------------------------------------------------------------- US-002


def test_register_owner_success_full_chain(client):
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["role"] == "owner"
    token = data["session"]["token"]

    engine = _sync_engine()
    with engine.connect() as conn:
        user = conn.execute(text("SELECT username, mobile, password_hash, email FROM hiveos.users")).one()
        # Mobile normalized to canonical +98 + 10 digits (US-002 validation rules).
        assert user.mobile == "+989121112233"
        assert user.password_hash.startswith("$argon2")  # never plain text (US-002 security)
        # Session: only the SHA-256 digest of the opaque token is stored (FR-004).
        token_hash = conn.execute(text("SELECT token_hash FROM hiveos.sessions")).scalar_one()
        assert token_hash == hashlib.sha256(token.encode()).hexdigest()
        member_role = conn.execute(
            text(
                "SELECT r.code, m.status FROM hiveos.role_assignments ra"
                " JOIN hiveos.roles r ON r.id = ra.role_id"
                " JOIN hiveos.organization_members m ON m.id = ra.member_id"
            )
        ).one()
        # IAM-002/007: owner role assigned through the membership.
        assert member_role == ("owner", "active")
        owner = conn.execute(
            text("SELECT owner_user_id FROM hiveos.organizations WHERE id = :id"), {"id": org_id}
        ).scalar_one()
        assert owner is not None  # US-002 FR-002: user connected to organization
        stored_hash = user.password_hash

    from backend.security import verify_password

    assert verify_password(stored_hash, "Str0ng!Pass")


def test_register_owner_audit_events(client):
    org_id = _bootstrap_org(client)
    _register_owner(client, org_id)
    with _sync_engine().connect() as conn:
        events = conn.execute(text("SELECT event FROM hiveos.audit_logs ORDER BY event")).scalars().all()
    # US-002 events.
    assert {"owner.created", "role.owner.assigned", "session.created"} <= set(events)


def test_register_owner_duplicate_mobile_rejected(client):
    first_org = _bootstrap_org(client)
    _register_owner(client, first_org)
    second_org = _bootstrap_org(client)
    # Same number in 0-prefix form: normalization must land on the same value.
    response = _register_owner(client, second_org, username="owner.two", mobile="09121112233")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MOBILE_ALREADY_EXISTS"
    assert _counts(client)["users"] == 1  # US-002 scenario 2: no second account


def test_register_owner_duplicate_email_case_insensitive(client):
    org_id = _bootstrap_org(client)
    _register_owner(client, org_id, email="Boss@Example.com")
    second_org = _bootstrap_org(client)
    response = _register_owner(
        client, second_org, username="owner.two", mobile="9122223344", email="boss@example.com"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


def test_register_owner_invalid_email_structure_rejected(client):
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id, mobile="9122223344", email="not-an-email")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_owner_invalid_mobile_shape_rejected(client):
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id, mobile="91211122")  # 8 digits - too short
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_owner_password_policy_enforced(client):
    org_id = _bootstrap_org(client)
    # No Latin symbol at all: the Persian character must NOT count as a symbol (PO fix 2026-08-18).
    response = _register_owner(client, org_id, password="Str0ngنا", confirm_password="Str0ngنا")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "PASSWORD_POLICY"
    assert "LATIN_SYMBOL" in body["error"]["message"]  # scenario 4: violated rules shown
    # US-002 scenario 4: no account is created.
    assert _counts(client)["users"] == 0


def test_register_owner_password_mismatch_rejected(client):
    org_id = _bootstrap_org(client)
    response = _register_owner(client, org_id, confirm_password="Different1!")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_MISMATCH"
    assert _counts(client)["users"] == 0


def test_register_owner_only_one_owner_per_organization(client):
    org_id = _bootstrap_org(client)
    assert _register_owner(client, org_id).status_code == 200
    response = _register_owner(
        client, org_id, username="owner.two", mobile="9122223344", email="two@example.com"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OWNER_ALREADY_EXISTS"


def test_register_owner_unknown_organization_404(client):
    response = _register_owner(client, str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


def test_register_owner_rolls_back_all_rows_on_server_error(client, monkeypatch):
    org_id = _bootstrap_org(client)

    def _boom(password: str) -> str:
        raise RuntimeError("simulated crash")

    # Failure after rows are staged: nothing may persist (US-001 AC scenario 3, atomicity).
    monkeypatch.setattr("backend.organization.service.hash_password", _boom)
    response = _register_owner(client, org_id)
    assert response.status_code == 500
    counts = _counts(client)
    assert counts["users"] == 0
    assert counts["sessions"] == 0
    assert counts["owner_created_audits"] == 0
    with _sync_engine().connect() as conn:
        owner = conn.execute(
            text("SELECT owner_user_id FROM hiveos.organizations WHERE id = :id"), {"id": org_id}
        ).scalar_one()
    assert owner is None


def test_username_availability_endpoint(client):
    org_id = _bootstrap_org(client)
    _register_owner(client, org_id)  # creates username 'owner.one'
    ok = client.get("/api/v1/auth/username-available", params={"username": "new.owner"})
    assert ok.status_code == 200
    assert ok.json()["data"] == {"username": "new.owner", "available": True, "reason": None}

    bad = client.get("/api/v1/auth/username-available", params={"username": "نام!؟"})
    assert bad.json()["data"]["available"] is False
    assert bad.json()["data"]["reason"] == "INVALID_FORMAT"

    taken = client.get("/api/v1/auth/username-available", params={"username": "owner.one"})
    assert taken.json()["data"]["available"] is False
    assert taken.json()["data"]["reason"] == "TAKEN"


def test_rate_limit_on_bootstrap_endpoints(client):
    for _ in range(10):
        _register_org(client)
    blocked = _register_org(client)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
