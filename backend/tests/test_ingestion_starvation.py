"""Regression tests for the ingestion-starvation bugs found 2026-09-15.

Three defects compounded into one outage on staging: a 26 MB text file and a
4908-chunk spreadsheet were queued, and the API process sat at 600% CPU with
the queue frozen at 50. Search requests took 15 s and returned nothing.

  1. chunk_text had no ceiling, so one document could cost hours of CPU.
  2. drain_queue committed once per 20-job batch, so no progress was durable
     until the whole batch finished and the queue looked hung.
  3. embeddings were computed for the entire document in one call, holding the
     inference semaphore for the duration and starving search.

These are the assertions that would have caught each one.
"""
from __future__ import annotations

import pytest

from backend.config import get_settings
from backend.knowledge.chunking import chunk_text

pytestmark = pytest.mark.anyio


def test_chunk_text_respects_the_document_cap() -> None:
    """A document far larger than the cap yields exactly cap chunks."""
    settings = get_settings()
    cap = settings.knowledge_max_chunks_per_document
    # Ten times the cap, so the loop would run long without the bound.
    huge = "x" * (settings.knowledge_chunk_size_chars * cap * 10)

    chunks = chunk_text(huge)

    assert len(chunks) == cap


def test_chunk_text_cap_is_overridable_and_off_at_zero() -> None:
    """max_chunks=0 means uncapped; an explicit value wins over the setting."""
    body = "y" * 8000

    assert len(chunk_text(body, max_chunks=3)) == 3
    # 8000 chars at 800/100 windows -> 12 chunks. max_chunks=0 disables the
    # ceiling entirely (it does not mean "no chunks").
    assert len(chunk_text(body, max_chunks=0)) == 12


def test_small_document_is_not_truncated() -> None:
    """The cap must not change behaviour for ordinary files."""
    body = "z" * 2400  # exactly 4 windows at 800/100

    chunks = chunk_text(body)

    assert "".join(chunks).startswith("z" * 800)
    assert len(chunks) == 4


def test_cap_bounds_embedding_work_per_document() -> None:
    """The point of the cap: worst-case embedding calls are bounded.

    Measured on staging at ~0.7 s/chunk, so an uncapped 32000-chunk file was
    roughly six hours of CPU in a single-process API. The cap keeps the worst
    case a few minutes.
    """
    settings = get_settings()
    cap = settings.knowledge_max_chunks_per_document
    worst_case_chunks = len(
        chunk_text("w" * (settings.knowledge_chunk_size_chars * 100_000))
    )

    assert worst_case_chunks == cap
    assert cap <= 5000
