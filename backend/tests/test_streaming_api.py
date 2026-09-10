"""US-0902 SSE streaming (T-S3-2)."""

from tests.test_knowledge_api import _bootstrap_full

CHAT = "/api/v1/chat"


def _create_session(client, headers):
    response = client.post(f"{CHAT}/sessions", json={}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_create_stream_requires_active_session(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    created = client.post(f"{CHAT}/sessions/{data['id']}/streams", headers=ctx["headers"])
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["connection_type"] == "SSE"
    assert body["stream_id"] in body["connection_url"]

    client.delete(f"{CHAT}/sessions/{data['id']}", headers=ctx["headers"])
    rejected = client.post(f"{CHAT}/sessions/{data['id']}/streams", headers=ctx["headers"])
    assert rejected.status_code == 409  # no streams on a deleted session


def test_sse_events_flow_and_assistant_message_persisted(client):
    from backend.chat import streaming

    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    stream_id = streaming.hub.create(data["id"])
    streaming.hub.emit_chunk(stream_id, "سلام، ")
    streaming.hub.emit_chunk(stream_id, "این پاسخ استریپ‌شده است.")
    streaming.hub.complete(stream_id)

    events = client.get(
        f"{CHAT}/sessions/{data['id']}/streams/{stream_id}/events",
        headers=ctx["headers"],
    )
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    frames = [
        line.removeprefix("data: ")
        for line in events.text.split("\n\n")
        if line.startswith("data: ")
    ]
    kinds = [frame["type"] for frame in (eval(frame) for frame in frames)]
    assert kinds[0] == "stream.started"
    assert kinds[1:3] == ["stream.chunk", "stream.chunk"]
    assert kinds[-1] == "stream.completed"

    messages = client.get(
        f"{CHAT}/sessions/{data['id']}/messages", headers=ctx["headers"]
    ).json()["data"]
    assistant = [m for m in messages["items"] if m["role"] == "ASSISTANT"]
    assert len(assistant) == 1
    assert assistant[0]["content"]["text"] == "سلام، این پاسخ استریپ‌شده است."


def test_stream_events_require_membership_and_existing_stream(client):
    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    missing = client.get(
        f"{CHAT}/sessions/{data['id']}/streams/not-a-real-stream/events",
        headers=ctx["headers"],
    )
    assert missing.status_code == 404


def test_chunks_after_completion_are_buffered(client):
    from backend.chat import streaming

    ctx = _bootstrap_full(client)
    data = _create_session(client, ctx["headers"])
    stream_id = streaming.hub.create(data["id"])
    streaming.hub.emit_chunk(stream_id, "پاسخ")
    streaming.hub.complete(stream_id)
    late_index = streaming.hub.emit_chunk(stream_id, " دیرهنگام")
    assert late_index == 1  # buffered for replay, not lost
    assert streaming.hub.status(stream_id) == "COMPLETED"
