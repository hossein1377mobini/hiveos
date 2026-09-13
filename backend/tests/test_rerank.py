"""Reranking acceptance tests (PO decision 2026-09-12).

The point of reranking is that it must never be able to break search: a
provider that is down, unconfigured or returning junk falls back to the
vector order instead of raising."""

import asyncio

import httpx

from backend.config import get_settings
from backend.knowledge import rerank as rerank_module


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def _stub(monkeypatch, payload, status=200):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):  # noqa: A002 - mirrors httpx
            return _Response(payload, status)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _configure(monkeypatch, enabled=True):
    # These cases drive the REMOTE provider; the local ONNX default has its own
    # file (test_local_inference.py).
    settings = get_settings().model_copy(
        update={"rerank_enabled": enabled, "rerank_provider": "remote"}
    )
    monkeypatch.setattr(rerank_module, "get_settings", lambda: settings)

    async def _read_setting(session, key):
        return {"base_url": "https://panel.example/v1", "api_key": "k"}

    # rerank.py binds read_setting at import time, so patch it there.
    monkeypatch.setattr(rerank_module, "read_setting", _read_setting)


def test_reranker_reorders_candidates(monkeypatch):
    _configure(monkeypatch)
    _stub(monkeypatch, {"results": [{"index": 2}, {"index": 0}, {"index": 1}]})
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b", "c"], 3))
    assert order == [2, 0, 1]


def test_disabled_reranker_keeps_the_vector_order(monkeypatch):
    _configure(monkeypatch, enabled=False)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b", "c"], 2))
    assert order == [0, 1]


def test_provider_error_falls_back_instead_of_raising(monkeypatch):
    _configure(monkeypatch)
    _stub(monkeypatch, {"error": "boom"}, status=500)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b"], 2))
    assert order == [0, 1]


def test_provider_outage_falls_back_instead_of_raising(monkeypatch):
    _configure(monkeypatch)

    class _Boom:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("no route")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b"], 2))
    assert order == [0, 1]


def test_out_of_range_and_duplicate_indices_are_repaired(monkeypatch):
    """A provider that repeats an index or invents one must not drop a
    document out of the result set."""
    _configure(monkeypatch)
    _stub(monkeypatch, {"results": [{"index": 1}, {"index": 1}, {"index": 9}]})
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b", "c"], 3))
    assert order == [1, 0, 2]

