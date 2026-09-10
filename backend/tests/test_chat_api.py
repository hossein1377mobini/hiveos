"""US-0901/US-0909 endpoints (T-S3-1)."""

from tests.test_knowledge_api import _bootstrap_full

CHAT = "/api/v1/chat"


def _create_session(client, headers, body=None):
    response = client.post(f"{CHAT}/sessions", json=body or {}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_create_session_defaults(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    assert data["status"] == "ACTIVE"
    assert data["settings"]["token_budget"] == 128000
    assert data["settings"]["temperature"] == 0.7
    assert data["context_state"]["message_count"] == 0


def test_create_session_validation_temperature(client):
    ctx = _bootstrap_full(client)
    response = client.post(
        f"{CHAT}/sessions",
        json={"settings": {"temperature": 3.5}},
        headers=ctx["headers"],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_sessions_filters_and_pagination(client):
    ctx = _bootstrap_full(client)
    first = _create_session(client, ctx["headers"], {"title": "قرارداد فروش"})
    _create_session(client, ctx["headers"], {"title": "پشتیبانی فنی", "pinned": True})
    _create_session(client, ctx["headers"], {"title": "بایگانی‌شده"})
    # archive the third
    archive = client.post(
        f"{CHAT}/sessions/{first['id']}/archive", headers=ctx["headers"]
    )

    active = client.get(f"{CHAT}/sessions", headers=ctx["headers"]).json()["data"]
    assert active["total_count"] == 2  # archived one excluded by default
    archived = client.get(
        f"{CHAT}/sessions", params={"status": "ARCHIVED"}, headers=ctx["headers"]
    ).json()["data"]
    assert archived["total_count"] == 1
    searched = client.get(
        f"{CHAT}/sessions", params={"search": "فروش"}, headers=ctx["headers"]
    ).json()["data"]
    assert searched["total_count"] == 0  # first was archived, not in default list
    assert archive.status_code == 200


def test_get_session_404_for_other_org_and_deleted(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    got = client.get(f"{CHAT}/sessions/{data['id']}", headers=ctx["headers"])
    assert got.status_code == 200

    deleted = client.delete(f"{CHAT}/sessions/{data['id']}", headers=ctx["headers"])
    assert deleted.status_code == 200
    gone = client.get(f"{CHAT}/sessions/{data['id']}", headers=ctx["headers"])
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "CHAT_SESSION_NOT_FOUND"

    # other org cannot even see the session id (org isolation); light
    # bootstrap (register + owner session, no OTP) to respect the auth limiter
    from tests.test_organization_api import _bootstrap_org, _register_owner

    org_id = _bootstrap_org(client)
    response2 = _register_owner(client, org_id, username="other.org", mobile="09123334444")
    assert response2.status_code == 200, response2.text
    other_headers = {"Authorization": f"Bearer {response2.json()['data']['session']['token']}"}
    cross = client.get(f"{CHAT}/sessions/{data['id']}", headers=other_headers)
    assert cross.status_code == 404  # ADR-024 tenant isolation


def test_patch_settings_optimistic_lock(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    response = client.patch(
        f"{CHAT}/sessions/{data['id']}/settings",
        json={"temperature": 1.5, "expected_version": data["version"]},
        headers=ctx["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["settings"]["temperature"] == 1.5
    assert response.json()["data"]["version"] == data["version"] + 1

    stale = client.patch(
        f"{CHAT}/sessions/{data['id']}/settings",
        json={"temperature": 0.2, "expected_version": data["version"]},
        headers=ctx["headers"],
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_archive_state_transitions(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    first = client.post(f"{CHAT}/sessions/{data['id']}/archive", headers=ctx["headers"])
    assert first.status_code == 200, first.text
    again = client.post(f"{CHAT}/sessions/{data['id']}/archive", headers=ctx["headers"])
    assert again.status_code == 409  # already archived
    unarchive = client.post(f"{CHAT}/sessions/{data['id']}/unarchive", headers=ctx["headers"])
    assert unarchive.status_code == 200
    assert unarchive.json()["data"]["status"] == "ACTIVE"
    not_archived = client.post(
        f"{CHAT}/sessions/{data['id']}/unarchive", headers=ctx["headers"]
    )
    assert not_archived.status_code == 409


def test_send_message_sequence_and_auto_title(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    first = client.post(
        f"{CHAT}/sessions/{data['id']}/messages",
        json={"text": "سلام، قرارداد جدید را خلاصه کن"},
        headers=ctx["headers"],
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["sequence"] == 1
    second = client.post(
        f"{CHAT}/sessions/{data['id']}/messages",
        json={"text": "ممنون"},
        headers=ctx["headers"],
    )
    assert second.json()["data"]["sequence"] == 2

    detail = client.get(f"{CHAT}/sessions/{data['id']}", headers=ctx["headers"]).json()["data"]
    assert detail["title"].startswith("سلام")  # auto-generated from first user message
    assert detail["context_state"]["message_count"] == 2


def test_message_idempotency_key(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    body = {"text": "پیام تستی"}
    headers = {**ctx["headers"], "Idempotency-Key": "abc-123"}
    first = client.post(f"{CHAT}/sessions/{data['id']}/messages", json=body, headers=headers)
    duplicate = client.post(f"{CHAT}/sessions/{data['id']}/messages", json=body, headers=headers)
    assert first.json()["data"]["id"] == duplicate.json()["data"]["id"]
    listing = client.get(
        f"{CHAT}/sessions/{data['id']}/messages", headers=ctx["headers"]
    ).json()["data"]
    assert listing["total_count"] == 1


def test_citations_rejected_on_user_message(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    response = client.post(
        f"{CHAT}/sessions/{data['id']}/messages",
        json={"text": "سوال", "citations": [{"doc_id": "x"}]},
        headers=ctx["headers"],
    )
    assert response.status_code == 400  # extra='forbid' -> VALIDATION_ERROR
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_messages_pagination_and_cursors(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    for index in range(5):
        client.post(
            f"{CHAT}/sessions/{data['id']}/messages",
            json={"text": f"پیام {index}"},
            headers=ctx["headers"],
        )
    page = client.get(
        f"{CHAT}/sessions/{data['id']}/messages",
        params={"page": 2, "page_size": 2},
        headers=ctx["headers"],
    ).json()["data"]
    assert [m["sequence"] for m in page["items"]] == [3, 4]
    assert page["total_count"] == 5 and page["has_more"] is True

    cursor = client.get(
        f"{CHAT}/sessions/{data['id']}/messages",
        params={"after": 3, "order": "asc"},
        headers=ctx["headers"],
    ).json()["data"]
    assert [m["sequence"] for m in cursor["items"]] == [4, 5]

    desc = client.get(
        f"{CHAT}/sessions/{data['id']}/messages",
        params={"order": "desc", "page_size": 2},
        headers=ctx["headers"],
    ).json()["data"]
    assert [m["sequence"] for m in desc["items"]] == [5, 4]


def test_archived_session_accepts_no_messages(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    client.post(f"{CHAT}/sessions/{data['id']}/archive", headers=ctx["headers"])
    response = client.post(
        f"{CHAT}/sessions/{data['id']}/messages",
        json={"text": "سلام"},
        headers=ctx["headers"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_NOT_ACTIVE"
