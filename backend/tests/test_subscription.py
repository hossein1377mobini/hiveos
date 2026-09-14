"""US-1207 minimal subscription (RG-21): panel-granted plan, expiry gate."""

from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import _bootstrap_full

EX = "/api/v1/executions"


def _set_sub(client, admin, org_id, plan, days):
    return client.post(
        f"{ADMIN}/organizations/{org_id}/subscription",
        json={"plan": plan, "days": days},
        headers=admin,
    )


def test_onboarding_status_carries_subscription(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _set_sub(client, admin, ctx["org_id"], "pro", 30)
    status = client.get("/api/v1/auth/onboarding-status", headers=ctx["headers"]).json()["data"]
    assert status["subscription"]["plan"] == "pro"
    assert status["subscription"]["expired"] is False


def test_onboarding_status_carries_the_callers_identity(client):
    """H1/D10: the app shell header has to name the signed-in person and their
    organization. Without this block it rendered a hardcoded «مدیر» and a generic
    role chip, so a user in a shared office could never confirm which account
    they were looking at."""
    ctx = _bootstrap_full(client)
    status = client.get("/api/v1/auth/onboarding-status", headers=ctx["headers"]).json()["data"]

    identity = status["identity"]
    assert identity["user_name"]
    assert identity["organization_name"]
    # Raw plan value: the Persian label belongs to the frontend's status registry,
    # so the API must not invent its own wording for it.
    assert identity["plan_label"] == status["subscription"]["plan"]


def test_identity_comes_from_the_session_not_from_a_hint(client):
    """The names describe the authenticated session, and nothing in the request
    can redirect them at another organization. A second, fully separate tenant is
    created here so there is a real other name to try to reach."""
    first = _bootstrap_full(client)

    # A second, independent organization with its own owner and session.
    second_org = client.post(
        "/api/v1/auth/register-organization",
        json={"name": "سازمان دوم", "industry": "fintech", "size": "10_50"},
    ).json()["data"]["organization_id"]
    second_owner = client.post(
        "/api/v1/auth/owner",
        json={
            "organization_id": second_org,
            "username": "owner.two",
            "mobile": "9129998877",
            "password": "Str0ng!Pass",
            "confirm_password": "Str0ng!Pass",
        },
    ).json()["data"]
    second_headers = {"Authorization": f"Bearer {second_owner['session']['token']}"}

    one = client.get("/api/v1/auth/onboarding-status", headers=first["headers"]).json()["data"]
    two = client.get("/api/v1/auth/onboarding-status", headers=second_headers).json()["data"]

    assert one["identity"]["organization_name"] != two["identity"]["organization_name"]
    assert one["identity"]["user_name"] == "owner.one"
    assert two["identity"]["user_name"] == "owner.two"

    # Asking with a hint pointing at the other tenant changes nothing.
    hinted = client.get(
        "/api/v1/auth/onboarding-status",
        headers=second_headers,
        params={"organization_id": first["org_id"]},
    ).json()["data"]
    assert hinted["identity"]["organization_name"] == two["identity"]["organization_name"]
    assert one["identity"]["organization_name"] not in str(hinted["identity"])


def test_expired_plan_blocks_runs_and_admin_extends(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _set_sub(client, admin, ctx["org_id"], "pro", 0)  # days=0 -> expired now
    # the gate fires at creation time (US-1207)
    blocked = client.post(EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"])
    assert blocked.status_code == 402, blocked.text
    body = blocked.json()
    assert body["error"]["code"] == "SUBSCRIPTION_EXPIRED"

    _set_sub(client, admin, ctx["org_id"], "pro", 30)
    created = client.post(
        EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"]
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "COMPLETED"


def test_orgs_list_carries_plan(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _set_sub(client, admin, ctx["org_id"], "basic", 14)
    orgs = client.get(f"{ADMIN}/organizations", headers=admin).json()["data"]["organizations"]
    row = next(o for o in orgs if o["id"] == ctx["org_id"])
    assert row["plan"] == "basic"
    assert row["plan_expires_at"] is not None


def test_subscription_requires_admin(client):
    ctx = _bootstrap_full(client)
    response = client.post(
        f"{ADMIN}/organizations/{ctx['org_id']}/subscription",
        json={"plan": "pro", "days": 30},
        headers=ctx["headers"],
    )
    assert response.status_code == 403
