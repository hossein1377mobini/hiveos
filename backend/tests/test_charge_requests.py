"""Charge-request loop: user files -> admin decides -> wallet credited (T-S3-8)."""

from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import _bootstrap_full

WALLET = "/api/v1/wallet"


def test_charge_request_loop(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)

    # 1. user files a request
    created = client.post(
        f"{WALLET}/charge-request",
        json={"amount": 200, "note": "card-to-card ref 12345"},
        headers=ctx["headers"],
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["status"] == "PENDING"

    # pending_request visible in wallet state
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["pending_request"]["amount"] == 200

    # 2. admin sees it in the queue
    queue = client.get(f"{ADMIN}/charge-requests", headers=admin).json()["data"]["requests"]
    assert any(r["id"] == body["request_id"] and r["amount"] == 200 for r in queue)

    # 3. approve -> wallet credited
    decided = client.post(
        f"{ADMIN}/charge-requests/{body['request_id']}/decision",
        json={"approve": True},
        headers=admin,
    ).json()["data"]
    assert decided["status"] == "APPROVED"
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 250
    assert state["pending_request"] is None
    assert state["transactions"][0]["kind"] == "CHARGE"

    # 4. decided request is terminal-once
    again = client.post(
        f"{ADMIN}/charge-requests/{body['request_id']}/decision",
        json={"approve": True},
        headers=admin,
    )
    assert again.status_code == 409  # terminal-once


def test_charge_request_reject(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    body = client.post(
        f"{WALLET}/charge-request", json={"amount": 50}, headers=ctx["headers"]
    ).json()["data"]
    decided = client.post(
        f"{ADMIN}/charge-requests/{body['request_id']}/decision",
        json={"approve": False},
        headers=admin,
    ).json()["data"]
    assert decided["status"] == "REJECTED"
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 50
    assert decided["balance"] is None


def test_charge_requests_require_admin(client):
    ctx = _bootstrap_full(client)
    client.post(
        f"{WALLET}/charge-request", json={"amount": 50}, headers=ctx["headers"]
    )
    noauth = client.get(f"{ADMIN}/charge-requests")
    assert noauth.status_code == 403
    user = client.get(f"{ADMIN}/charge-requests", headers=ctx["headers"])
    assert user.status_code == 403


def test_admin_organizations_list(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    # materialize the wallet row (lazy on first read)
    client.get("/api/v1/wallet", headers=ctx["headers"])
    orgs = client.get(f"{ADMIN}/organizations", headers=admin).json()["data"]["organizations"]
    assert any(o["id"] == ctx["org_id"] and o["balance"] == 50 for o in orgs)
