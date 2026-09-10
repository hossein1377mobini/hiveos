"""US-301..306 acceptance tests (T-S3-3)."""

from tests.test_knowledge_api import _bootstrap_full

EX = "/api/v1/executions"


def _create_session(client, headers):
    return client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["data"]


def test_create_execution_validation_and_idempotency(client):
    ctx = _bootstrap_full(client)
    # empty input rejected
    empty = client.post(EX, json={}, headers=ctx["headers"])
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "VALIDATION_ERROR"

    body = {"input": {"text": "سلام"}, "chat_session_id": None}
    headers = {**ctx["headers"], "Idempotency-Key": "exec-1"}
    first = client.post(EX, json=body, headers=headers)
    assert first.status_code == 200, first.text
    duplicate = client.post(EX, json=body, headers=headers)
    assert first.json()["data"]["id"] == duplicate.json()["data"]["id"]
    assert first.json()["data"]["status"] == "PENDING"
    assert first.json()["data"]["agent_id"] == "hive-mind-default"


def test_full_lifecycle_start_run_complete(client):
    ctx = _bootstrap_full(client)
    chat = _create_session(client, ctx["headers"])
    client.post(f"/api/v1/chat/sessions/{chat['id']}/messages", json={"text": "قدیم"}, headers=ctx["headers"])
    created = client.post(
        EX,
        json={"input": {"text": "خلاصه کن"}, "chat_session_id": chat["id"]},
        headers=ctx["headers"],
    ).json()["data"]

    started = client.post(f"{EX}/{created['id']}/start", headers=ctx["headers"]).json()["data"]
    assert started["status"] == "RUNNING"
    # US-304: context snapshot built from the chat session
    assert started["context_snapshot"]["chat_session_id"] == chat["id"]
    assert started["context_snapshot"]["message_count"] == 1

    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "COMPLETED"
    assert done["output"]["stub"] is True
    assert done["completed_at"] is not None

    # start again -> conflict
    restart = client.post(f"{EX}/{created['id']}/start", headers=ctx["headers"])
    assert restart.status_code == 409


def test_cancel_rules(client):
    ctx = _bootstrap_full(client)
    created = client.post(EX, json={"input": {"text": "لغو کن"}}, headers=ctx["headers"]).json()["data"]
    cancelled = client.post(f"{EX}/{created['id']}/cancel", headers=ctx["headers"]).json()["data"]
    assert cancelled["status"] == "CANCELLED"
    again = client.post(f"{EX}/{created['id']}/cancel", headers=ctx["headers"])
    assert again.status_code == 409  # already terminal


def test_execution_requires_chat_session_access(client):
    ctx = _bootstrap_full(client)
    response = client.post(
        EX,
        json={"input": {"text": "سلام"}, "chat_session_id": "00000000-0000-0000-0000-000000000001"},
        headers=ctx["headers"],
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHAT_SESSION_NOT_FOUND"


def test_list_filter_and_org_isolation(client):
    ctx = _bootstrap_full(client)
    first = client.post(EX, json={"input": {"text": "یکی"}}, headers=ctx["headers"]).json()["data"]
    second = client.post(EX, json={"input": {"text": "دو"}}, headers=ctx["headers"]).json()["data"]
    client.post(f"{EX}/{second['id']}/cancel", headers=ctx["headers"])

    running = client.get(EX, params={"status": "PENDING"}, headers=ctx["headers"]).json()["data"]
    assert running["total_count"] == 1
    assert running["items"][0]["id"] == first["id"]

    # other org cannot see the execution (ADR-024)
    from tests.test_organization_api import _bootstrap_org, _register_owner

    org_id = _bootstrap_org(client)
    response2 = _register_owner(client, org_id, username="other.org2", mobile="09123335555")
    other_headers = {"Authorization": f"Bearer {response2.json()['data']['session']['token']}"}
    cross = client.get(f"{EX}/{first['id']}", headers=other_headers)
    assert cross.status_code == 404
