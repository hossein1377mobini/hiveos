"""US-004 — POST /api/v1/workspaces/initialize (flip the US-001 Workspace to ready).

The Workspace already exists (one per org, created in US-001 with status
``pending`` and default settings). This endpoint flips it to ``ready``, inherits
settings from the Organization (US-001 defaults: fa-IR / Asia/Tehran / ...), is
idempotent, and is protected by ``require_org_session`` (no valid ``session``
cookie → 401; org not yet active → 409).

Every test provisions state through the API: org (US-001) → owner (US-002) →
OTP send/verify (US-003, via the recording SMS provider).
"""

PHONE = "+989123456780"

_EXPECTED_SETTINGS = {
    "language": "fa-IR",
    "timeZone": "Asia/Tehran",
    "dateFormat": "YYYY/MM/DD",
    "numberFormat": "fa-IR",
    "defaultLocale": "fa-IR",
}


def _seat_session(client, make_owner, org) -> None:
    """Create the owner and re-seat the Secure ``session`` cookie.

    The owner response issues the session token as a ``Secure`` HttpOnly
    cookie. TestClient transports over ``http://testserver``, so httpx stores
    the cookie but will not *send* a Secure cookie over http. Wave-1 already
    works around this exact issue for the (also Secure) ``onboarding`` cookie by
    re-setting it as a plain cookie; we do the same here so the token actually
    travels on the next request.
    """
    make_owner(org, phone=PHONE)
    token = client.cookies.get("session")
    assert token, "owner creation must issue a session cookie"
    client.cookies.set("session", token)


def _activate_org(client, make_org, make_owner, sms_provider) -> dict:
    """Full happy onboarding: org + owner + OTP verify → active org.

    Returns the US-001 org dict (``{"id", "onboarding"}``). The owner's
    ``session`` cookie is re-seated (plain) in the shared client jar afterwards.
    """
    org = make_org()
    _seat_session(client, make_owner, org)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]
    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200, resp.text
    return org


def test_initialize_workspace_happy_path(client, db, make_org, make_owner, sms_provider):
    org = _activate_org(client, make_org, make_owner, sms_provider)

    resp = client.post("/api/v1/workspaces/initialize")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["settings"] == _EXPECTED_SETTINGS

    workspace_id = body["workspaceId"]
    assert workspace_id

    # US-001 created exactly ONE workspace for the org; the same row that was
    # ``pending`` is now ``ready`` (no second workspace was spawned).
    rows = db.fetch(
        "SELECT id, status FROM workspaces WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(rows) == 1
    assert str(rows[0]["id"]) == workspace_id
    assert rows[0]["status"] == "ready"


def test_initialize_workspace_idempotent(client, db, make_org, make_owner, sms_provider):
    org = _activate_org(client, make_org, make_owner, sms_provider)

    first = client.post("/api/v1/workspaces/initialize")
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/workspaces/initialize")
    assert second.status_code == 201, second.text

    # Same workspace id on the repeat call; still exactly one row.
    assert second.json()["workspaceId"] == first.json()["workspaceId"]
    assert second.json()["status"] == "ready"
    rows = db.fetch(
        "SELECT id FROM workspaces WHERE organization_id = $1::uuid", org["id"]
    )
    assert len(rows) == 1


def test_initialize_workspace_org_not_active_conflict(client, make_org, make_owner):
    # Owner created (session issued) but OTP never verified → org still pending.
    org = make_org()
    _seat_session(client, make_owner, org)

    resp = client.post("/api/v1/workspaces/initialize")

    assert resp.status_code == 409
    assert resp.json()["error"] == "conflict"


def test_initialize_workspace_no_session_unauthorized(client):
    resp = client.post("/api/v1/workspaces/initialize")

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"
