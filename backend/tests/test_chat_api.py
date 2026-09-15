"""US-0901/US-0909 endpoints (T-S3-1)."""

from tests.test_knowledge_api import _bootstrap_full

CHAT = "/api/v1/chat"


def _create_session(client, headers, body=None):
    response = client.post(f"{CHAT}/sessions", json=body or {}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_an_empty_session_is_never_listed(client):
    """PO request 2026-09: "no session may be empty - delete it so it is not shown".

    The client opens a session speculatively (the "new chat" button POSTs
    /chat/sessions before anything is typed), so pressing it and typing nothing
    left an empty row. It must not appear in the list - and it must also not
    accumulate: an abandoned one is deleted once it is older than the grace
    period.
    """
    ctx = _bootstrap_full(client)
    empty = _create_session(client, ctx["headers"], {"title": "گفتگوی جدید"})
    listed = client.get(f"{CHAT}/sessions", headers=ctx["headers"]).json()["data"]
    assert listed["total_count"] == 0
    assert listed["items"] == []

    # It is still addressable by id - the user may be about to type into it.
    assert (
        client.get(f"{CHAT}/sessions/{empty['id']}", headers=ctx["headers"]).status_code == 200
    )

    # A session that DOES have a message is listed, and survives the cleanup.
    kept = _create_session(client, ctx["headers"], {"title": "گفتگوی واقعی"})
    _give_a_message(client, ctx["headers"], kept["id"])
    listed = client.get(f"{CHAT}/sessions", headers=ctx["headers"]).json()["data"]
    assert [str(row["id"]) for row in listed["items"]] == [str(kept["id"])]


def test_list_sessions_purges_an_abandoned_empty_session_past_the_grace(client):
    """The rows must not accumulate forever (partner of the filter above).

    The guard is the grace period: a fresh empty session is never touched,
    because deleting one the user is about to type into would make their send
    fail with CHAT_SESSION_NOT_FOUND.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine, text

    from backend.config import get_settings, to_sync_database_url

    ctx = _bootstrap_full(client)
    stale = _create_session(client, ctx["headers"], {"title": "رهاشده"})
    fresh = _create_session(client, ctx["headers"], {"title": "تازه"})

    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.begin() as conn:
        # Age one of them past the one-hour grace period.
        conn.execute(
            text("UPDATE hiveos.chat_sessions SET created_at = :t WHERE id = :id"),
            {"t": datetime.now(UTC) - timedelta(hours=2), "id": stale["id"]},
        )
    engine.dispose()

    listed = client.get(f"{CHAT}/sessions", headers=ctx["headers"]).json()["data"]
    assert listed["total_count"] == 0

    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        ids = conn.execute(text("SELECT id FROM hiveos.chat_sessions")).scalars().all()
    engine.dispose()
    # The abandoned one is GONE; the one created seconds ago is untouched.
    assert [str(row) for row in ids] == [str(fresh["id"])]


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


def _give_a_message(client, headers, session_id, text="سلام"):
    """A session with no messages is filtered out; every listed one needs one."""
    response = client.post(
        f"{CHAT}/sessions/{session_id}/messages", json={"text": text}, headers=headers
    )
    assert response.status_code == 200, response.text


def test_list_sessions_filters_and_pagination(client):
    ctx = _bootstrap_full(client)
    first = _create_session(client, ctx["headers"], {"title": "قرارداد فروش"})
    second = _create_session(client, ctx["headers"], {"title": "پشتیبانی فنی", "pinned": True})
    third = _create_session(client, ctx["headers"], {"title": "بایگانی‌شده"})
    for session in (first, second, third):
        _give_a_message(client, ctx["headers"], session["id"])
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
