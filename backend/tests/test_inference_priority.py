"""The ingestion worker must not monopolise the inference semaphore.

Staging 2026-09-15: with a large document draining, an interactive query embed
measured 6.96 s and a 20-candidate rerank 14.56 s; the same calls warm and
uncontended measure 0.03 s and 3.8 s. Search took 8-15 s and returned nothing
while the queue advanced. These tests pin the mechanism that fixes it.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.knowledge import onnx_runtime

pytestmark = pytest.mark.anyio


def test_interactive_flag_is_off_by_default() -> None:
    assert onnx_runtime.interactive_inference_pending() is False


def test_interactive_flag_set_for_the_duration_of_the_block() -> None:
    with onnx_runtime.interactive_inference():
        assert onnx_runtime.interactive_inference_pending() is True
    assert onnx_runtime.interactive_inference_pending() is False


def test_flag_clears_even_when_the_block_raises() -> None:
    with pytest.raises(ValueError):
        with onnx_runtime.interactive_inference():
            raise ValueError("boom")
    assert onnx_runtime.interactive_inference_pending() is False


def test_nested_interactive_blocks_unwind_correctly() -> None:
    with onnx_runtime.interactive_inference():
        with onnx_runtime.interactive_inference():
            assert onnx_runtime.interactive_inference_pending() is True
        assert onnx_runtime.interactive_inference_pending() is True
    assert onnx_runtime.interactive_inference_pending() is False


async def test_background_embed_waits_for_the_interactive_flag_to_clear(
    monkeypatch,
) -> None:
    """The worker must not take the semaphore while a user call is pending.

    embed_background is replaced by a stub that records whether it ever
    observed a pending interactive call, so the assertion is about the
    ordering the worker promises rather than about ONNX itself.
    """
    seen: list[bool] = []
    real_sleep = asyncio.sleep

    async def _record_then_call(texts):
        # Mirror the production yield loop, then record what it observed.
        for _ in range(100):
            if not onnx_runtime.interactive_inference_pending():
                break
            await real_sleep(0.01)
        seen.append(onnx_runtime.interactive_inference_pending())
        return [[0.0] for _ in texts]

    # embed_texts_background imports this name lazily from onnx_runtime, so the
    # patch has to land on the defining module.
    monkeypatch.setattr(onnx_runtime, "embed_background", _record_then_call)

    from backend.knowledge import embeddings

    # The test settings default to the mock provider, which has no shared
    # semaphore and so returns early. Force the ONNX branch that this test is
    # actually about.
    class _OnnxSettings:
        embedding_provider = "onnx"

    monkeypatch.setattr(embeddings, "get_settings", lambda: _OnnxSettings())

    async def _run():
        with onnx_runtime.interactive_inference():
            task = asyncio.create_task(embeddings.embed_texts_background(["x"]))
            # Give the background task a chance to start and observe the flag.
            await real_sleep(0.05)
        await task

    await _run()
    assert seen == [False], (
        "background embedding proceeded while an interactive call was pending"
    )

async def test_background_embed_releases_the_semaphore_between_batches(
    monkeypatch,
) -> None:
    """The worker must not hold an inference slot for a whole document.

    The first fix added a priority check in front of embed_background, but the
    semaphore was still taken once around every batch, so the check ran once per
    document. A 2000-chunk file therefore held the slots for minutes and
    searches queued behind it - measured on staging as 15.5 s for a single lone
    search and 0.13 searches/s, with the API at 216% CPU.

    This counts the acquisitions: with N batches there must be N of them, not 1.
    """
    acquisitions: list[int] = []

    class _FakeSemaphore:
        async def __aenter__(self):
            acquisitions.append(1)
            return self

        async def __aexit__(self, *exc):
            return False

    class _Settings:
        embedding_provider = "onnx"
        embedding_onnx_dir = "unused"
        embedding_onnx_max_tokens = 8
        local_inference_batch_size = 4

    # get_settings is imported inside the function body, so the patch has to
    # land on the defining module rather than on onnx_runtime's namespace.
    from backend import config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _Settings())
    monkeypatch.setattr(onnx_runtime, "_get_semaphore", lambda: _FakeSemaphore())

    # _embed_sync is called through asyncio.to_thread, so the stub must be a
    # plain function; an async one is passed to the thread and never awaited.
    def _fake_embed_sync(model_dir, texts, max_length, batch_size):
        return [[0.0] for _ in texts]

    monkeypatch.setattr(onnx_runtime, "_embed_sync", _fake_embed_sync)

    # 10 texts at a batch size of 4 => 3 acquisitions.
    vectors = await onnx_runtime.embed_background([f"t{i}" for i in range(10)])

    assert len(vectors) == 10
    assert len(acquisitions) == 3, (
        "the semaphore must be taken once per batch; taking it once per document "
        "lets ingestion hold every inference slot until the file is finished"
    )


async def test_background_embed_handles_an_empty_input(monkeypatch) -> None:
    """An empty document must not take a slot or divide by a zero batch size."""

    class _Settings:
        embedding_provider = "onnx"
        embedding_onnx_dir = "unused"
        embedding_onnx_max_tokens = 8
        local_inference_batch_size = 4

    from backend import config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _Settings())
    assert await onnx_runtime.embed_background([]) == []
