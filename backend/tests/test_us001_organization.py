"""US-001 — POST /api/v1/organizations (register organization)."""

from app.errors import ConflictError


def _payload(name: str = "Acme Test Org") -> dict:
    return {
        "displayName": name,
        "industry": "Software",
        "companySize": "lt_10",
        "businessDescription": {
            "whatYouDo": "We build onboarding and QA tooling for teams.",
            "productsServices": "Automated test and onboarding software.",
        },
        "aiModel": {
            "mode": "online",
            "provider": "openai",
            "apiKey": "sk-test-not-a-real-key-1234567890",
        },
    }


def test_create_organization_happy_path(client):
    resp = client.post("/api/v1/organizations", json=_payload())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Acme Test Org"
    assert body["status"] == "pending_owner_registration"
    assert body["id"]
    assert body["tenantId"]
    assert body["workspaceId"]
    assert body["createdAt"]


def test_create_organization_persists_tenant_workspace_audit(client, db, make_org):
    org = make_org()

    assert db.fetchone("SELECT count(*) AS n FROM tenants")["n"] == 1
    assert db.fetchone("SELECT count(*) AS n FROM workspaces")["n"] == 1
    assert (
        db.fetchone("SELECT count(*) AS n FROM audit_logs WHERE action = 'organization.created'")[
            "n"
        ]
        == 1
    )

    row = db.fetchone(
        "SELECT status, tenant_id, workspace_id FROM organizations WHERE id = $1::uuid",
        org["id"],
    )
    assert row["status"] == "pending_owner_registration"
    assert row["tenant_id"] is not None
    assert row["workspace_id"] is not None


def test_short_display_name_rejected(client):
    resp = client.post("/api/v1/organizations", json=_payload(name="Ab"))

    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_missing_business_description_rejected(client):
    payload = _payload()
    del payload["businessDescription"]
    resp = client.post("/api/v1/organizations", json=payload)

    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_bad_company_size_rejected(client):
    payload = _payload()
    payload["companySize"] = "mega_huge"
    resp = client.post("/api/v1/organizations", json=payload)

    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_failed_creation_rolls_back_everything(client, db, monkeypatch):
    """A mid-transaction failure must not leave a half-written tenant.

    ``encrypt_secret`` runs *after* the Tenant has been flushed (during
    Organization construction), so raising there provokes a real rollback of the
    ambient transaction and proves no partial rows survive.
    """

    def _boom(_value: str) -> str:
        raise ConflictError("simulated mid-transaction failure")

    monkeypatch.setattr("app.security.encrypt_secret", _boom)

    resp = client.post("/api/v1/organizations", json=_payload())

    assert resp.status_code == 409
    assert db.fetchone("SELECT count(*) AS n FROM tenants")["n"] == 0
    assert db.fetchone("SELECT count(*) AS n FROM organizations")["n"] == 0
    assert db.fetchone("SELECT count(*) AS n FROM workspaces")["n"] == 0
    assert db.fetchone("SELECT count(*) AS n FROM audit_logs")["n"] == 0
