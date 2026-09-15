"""A search must not hold a database transaction across its slow calls.

Staging 2026-09-15, 20 concurrent users: a search session sat "idle in
transaction" for 3 m 16 s after its knowledge_chunks SELECT. It was blocked on
(or blocking) "UPDATE hiveos.sessions SET expires_at", and because every
authenticated request refreshes its own session row, that one held transaction
produced lock waits that stalled the entire API - including endpoints that run
no inference at all. /api/health, which touches no database, stayed at 0.47 s
p50 throughout, which is what pointed at the database rather than the event loop.

semantic_search used to open a transaction in is_org_admin, hold it through the
query embed (which can wait up to the inference queue timeout), then hold the
SELECT's transaction through reranking (seconds per call). It now commits before
each slow call. These tests pin the commit-before-slow-call ordering.
"""

from __future__ import annotations

import pytest

from backend.knowledge import search as search_module

pytestmark = pytest.mark.anyio


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeChunk:
    def __init__(self, index, content):
        self.asset_id = "asset-1"
        self.chunk_index = index
        self.content = content


class _FakeSession:
    """Records the order of commits, queries and inference, and tracks tx state."""

    def __init__(self, rows):
        self.events: list[str] = []
        self.in_transaction = True
        self._rows = rows

    async def execute(self, *args, **kwargs):
        self.events.append("select")
        return _FakeResult(self._rows)

    async def commit(self):
        self.events.append("commit")
        self.in_transaction = False


def _rows(count: int = 2):
    return [
        (_FakeChunk(index, f"chunk {index}"), f"doc-{index}", 0.2 + index * 0.1)
        for index in range(count)
    ]


async def _run_search(monkeypatch, rows):
    session = _FakeSession(rows)
    seen: dict[str, object] = {}

    async def _no_admin(*args, **kwargs):
        return False

    async def _embed(query):
        # The embed happens between the two commits; nothing may be open here.
        seen["in_transaction_at_embed"] = session.in_transaction
        return [0.0, 1.0]

    async def _rerank(query, documents, limit):
        # The assertion that matters: no transaction is held across reranking.
        seen["in_transaction_at_rerank"] = session.in_transaction
        seen["documents"] = list(documents)
        return list(range(len(documents)))

    async def _audit(*args, **kwargs):
        return None

    monkeypatch.setattr(search_module, "is_org_admin", _no_admin)
    monkeypatch.setattr(search_module, "embed_one", _embed)
    monkeypatch.setattr(search_module, "rerank", _rerank)
    monkeypatch.setattr(search_module, "record_audit", _audit)
    monkeypatch.setattr(search_module, "visible_to", lambda *a, **k: True)

    result = await search_module.semantic_search(session, "org-1", "قناری", 5, "user-1")
    return session, seen, result


async def test_search_holds_no_transaction_while_reranking(monkeypatch) -> None:
    session, seen, result = await _run_search(monkeypatch, _rows())

    assert seen["in_transaction_at_rerank"] is False, (
        "rerank ran with a database transaction open: the session is left idle "
        "in transaction for the whole cross-encoder call, which blocks writers"
    )
    assert result["results"], "the reranked hits must still come back"


async def test_search_holds_no_transaction_while_embedding(monkeypatch) -> None:
    _, seen, _ = await _run_search(monkeypatch, _rows())

    assert seen["in_transaction_at_embed"] is False, (
        "the query embed ran with the transaction opened by the admin check still "
        "open; that is the hold that lasted 3 m 16 s on staging"
    )


async def test_search_commits_before_each_slow_call(monkeypatch) -> None:
    session, _, _ = await _run_search(monkeypatch, _rows())

    # Two slow calls (embed, rerank) means two guards, so the read transaction
    # opened by is_org_admin is closed before the embed and the SELECT's own
    # transaction is closed before the rerank.
    assert session.events.count("commit") >= 2, session.events
    assert session.events.index("commit") < session.events.index("select"), (
        "the transaction opened by the admin check must close before the SELECT"
    )


async def test_search_does_not_rerank_when_nothing_was_recalled(monkeypatch) -> None:
    """No candidates means no rerank and still no dangling transaction."""
    session, seen, result = await _run_search(monkeypatch, [])

    assert "in_transaction_at_rerank" not in seen
    assert session.in_transaction is False or "commit" in session.events
    assert result["results"] == []
