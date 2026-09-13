"""US-212/US-227 + PO decision 2026-09-12: local ONNX inference on the server.

The failure mode these tests pin is a reranker that breaks search. Reranking
is a quality stage, never a correctness stage: if the local model is missing,
crashes or returns junk, the vector order must survive untouched."""

import asyncio

from backend.config import get_settings
from backend.knowledge import onnx_runtime
from backend.knowledge import rerank as rerank_module


def _configure(monkeypatch, **overrides):
    settings = get_settings().model_copy(update=overrides)
    monkeypatch.setattr(rerank_module, "get_settings", lambda: settings)
    return settings


def test_local_reranker_orders_by_score(monkeypatch):
    _configure(monkeypatch, rerank_provider="onnx", rerank_enabled=True)

    async def _score(query, documents):
        return [0.1, 0.9, 0.5][: len(documents)]

    monkeypatch.setattr(onnx_runtime, "score", _score)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b", "c"], 3))
    assert order == [1, 2, 0]


def test_local_reranker_respects_top_k(monkeypatch):
    _configure(monkeypatch, rerank_provider="onnx", rerank_enabled=True)

    async def _score(query, documents):
        return [0.1, 0.9, 0.5][: len(documents)]

    monkeypatch.setattr(onnx_runtime, "score", _score)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b", "c"], 2))
    assert order == [1, 2]


def test_missing_model_falls_back_to_vector_order(monkeypatch):
    _configure(monkeypatch, rerank_provider="onnx", rerank_enabled=True)

    async def _boom(query, documents):
        raise RuntimeError("no ONNX graph at /opt/models/...")

    monkeypatch.setattr(onnx_runtime, "score", _boom)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b", "c"], 3))
    assert order == [0, 1, 2]


def test_disabled_provider_skips_inference_entirely(monkeypatch):
    _configure(monkeypatch, rerank_provider="off")
    called = []

    async def _score(query, documents):
        called.append(1)
        return [0.0] * len(documents)

    monkeypatch.setattr(onnx_runtime, "score", _score)
    order = asyncio.run(rerank_module.rerank("پرسش", ["a", "b"], 2))
    assert order == [0, 1]
    assert called == []


def test_single_document_needs_no_reranking(monkeypatch):
    _configure(monkeypatch, rerank_provider="onnx", rerank_enabled=True)
    order = asyncio.run(rerank_module.rerank("پرسش", ["only"], 5))
    assert order == [0]


def test_concurrency_limit_is_at_least_one(monkeypatch):
    settings = get_settings().model_copy(update={"local_inference_concurrency": 0})
    # _get_semaphore imports get_settings inside the function, so the patch has
    # to land on backend.config rather than on this module.
    monkeypatch.setattr("backend.config.get_settings", lambda: settings)
    onnx_runtime._semaphore = None  # force a rebuild from the patched settings
    try:
        semaphore = onnx_runtime._get_semaphore()
        assert semaphore._value == 1
    finally:
        onnx_runtime._semaphore = None
