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
