"""Ingestion must not hold a transaction across embedding.

Staging 2026-09-15, after the inline-processing change: an ingestion transaction
sat "idle in transaction" for 1 m 30 s whose last statement was
"DELETE FROM hiveos.knowledge_chunks WHERE asset_id = $1 AND organization_id = $2"
- that is replace_chunks. It held the deleted rows' locks for the whole of the
first embed_texts call, and because both inference slots were busy (the queue
behind it), that wait is minutes rather than seconds. Every authenticated request
refreshes its own sessions row, so they queued behind it: the live suite's
classify calls timed out at 125 s with an empty body.

process_job replaced every chunk and only committed after the first embed batch
had finished. It now commits the replacement before it starts embedding, so the
locks are released before the slow part AND the replacement is durable even if
the embed never lands (the job stays 'processing' and the orphan reclaim in
drain_queue picks it up).

These tests pin the ordering, because the failure is invisible in a unit test
that only asserts the chunks end up with embeddings.
"""

from __future__ import annotations

import pytest

from backend.knowledge import worker as worker_module

pytestmark = pytest.mark.anyio


class _FakeChunk:
    def __init__(self, index: int):
        self.asset_id = "asset-1"
        self.chunk_index = index
        self.content = f"chunk {index}"
        self.embedding = None


class _FakeAsset:
    id = "asset-1"
    organization_id = "org-1"
    source_id = None
    name = "doc.txt"
    extension = "txt"
    size_bytes = 10
    asset_type = "text"
    extracted_text = None
    asset_metadata = None
    status = "queued"


class _FakeJob:
    id = "job-1"
    asset_id = "asset-1"
    organization_id = "org-1"
    job_type = "create"
    asset_version = 1
    attempt_count = 0
    status = "processing"
    error_detail = None
    updated_at = None


class _FakeSession:
    """Records the order of the operations process_job performs."""

    def __init__(self):
        self.events: list[str] = []
        self.in_transaction = True

    async def get(self, model, key):
        self.events.append("get")
        return _FakeAsset() if getattr(model, "__name__", "") == "KnowledgeAsset" else None

    async def commit(self):
        self.events.append("commit")
        self.in_transaction = False

    async def rollback(self):
        self.events.append("rollback")
        self.in_transaction = False

    def add(self, obj):
        pass


@pytest.fixture
def patched(monkeypatch):
    """Replace the costly steps with recorders, keeping the ordering intact."""
    state = {"rows": [_FakeChunk(0), _FakeChunk(1), _FakeChunk(2)]}

    monkeypatch.setattr(worker_module, "classify_asset", lambda asset, folder: {
        "asset_type": "text", "pipeline": "text",
    })
    monkeypatch.setattr(worker_module, "extract_text", lambda asset, folder: "متن سند برای آزمون")

    async def fake_replace_chunks(session, asset, text):
        session.events.append("replace_chunks")
        return state["rows"]

    async def fake_embed(texts):
        session = state["session"]
        state["in_tx_at_embed"] = session.in_transaction
        session.events.append("embed")
        return [[0.0] * 4 for _ in texts]

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(worker_module, "replace_chunks", fake_replace_chunks)
    monkeypatch.setattr(worker_module, "embed_texts_background", fake_embed)
    monkeypatch.setattr(worker_module, "record_audit", fake_audit)
    monkeypatch.setattr(worker_module, "build_metadata", lambda asset: {})
    return state


async def test_ingestion_does_not_embed_inside_a_transaction(patched):
    """The invariant: no open transaction while inference runs."""
    session = _FakeSession()
    patched["session"] = session

    await worker_module.process_job(session, _FakeJob())

    assert patched.get("in_tx_at_embed") is False, (
        "embedding happened with a transaction still open; that is the state that "
        "held knowledge_chunks locks for 1 m 30 s and stalled every other request"
    )


async def test_the_chunk_replacement_is_committed_before_the_first_embed(patched):
    session = _FakeSession()
    patched["session"] = session

    await worker_module.process_job(session, _FakeJob())

    events = session.events
    replace_at = events.index("replace_chunks")
    embed_at = events.index("embed")
    commits_before_embed = [e for e in events[replace_at:embed_at] if e == "commit"]
    assert commits_before_embed, (
        f"replace_chunks was not followed by a commit before embedding: {events}"
    )


async def test_an_empty_document_still_completes_without_embedding(patched):
    """A document that produced no chunks must not be left 'processing'."""
    patched["rows"] = []
    session = _FakeSession()
    patched["session"] = session
    job = _FakeJob()

    await worker_module.process_job(session, job)

    assert job.status == "completed"
    assert "embed" not in session.events
