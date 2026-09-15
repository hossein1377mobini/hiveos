"""Normalize + chunk extracted text (US-210/US-211, T-S2-5).

- normalize_text: NFKC unicode folding, zero-width stripping, whitespace
  collapsing (US-210); keeps Persian text intact otherwise.
- chunk_text: fixed-size windows with overlap (US-211, config-driven).
- build_chunks / replace_chunks: worker-side persistence; a new asset
  version replaces the previous version's chunks wholesale.
"""

import time
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models import KnowledgeAsset, KnowledgeChunk

_ZERO_WIDTH = "".join(chr(code) for code in (0x200B, 0x200C, 0x200D, 0xFEFF))


def normalize_text(raw: str) -> str:
    """US-210: unicode NFKC, zero-width removal, whitespace collapse."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    for character in _ZERO_WIDTH:
        text = text.replace(character, "")
    return " ".join(text.split())


def chunk_text(normalized: str, max_chunks: int | None = None) -> list[str]:
    """US-211: fixed-size chunks with overlap; empty input -> no chunks.

    max_chunks bounds ONE document. Embedding is CPU-bound and single-process,
    so without a ceiling one very large file holds the inference semaphore for
    hours and every search request waits behind it. Defaults to
    knowledge_max_chunks_per_document.
    """
    settings = get_settings()
    size = settings.knowledge_chunk_size_chars
    overlap = settings.knowledge_chunk_overlap_chars
    if size <= 0:
        raise ValueError("knowledge_chunk_size_chars must be positive")
    overlap = min(overlap, size - 1)
    if not normalized:
        return []
    cap = settings.knowledge_max_chunks_per_document if max_chunks is None else max_chunks
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        if cap > 0 and len(chunks) >= cap:
            break
        chunks.append(normalized[start : start + size])
        if start + size >= len(normalized):
            break
        start += size - overlap
    return chunks

def build_metadata(asset: KnowledgeAsset) -> dict:
    """US-208: the pipeline metadata bag stored on the asset."""
    return {
        "name": asset.name,
        "extension": asset.extension,
        "size_bytes": asset.size_bytes,
        "asset_type": asset.asset_type,
        "pipeline": asset.pipeline,
        "version": asset.version,
        "origin": "upload" if asset.source_id is None else "folder_scan",
        "rel_path": asset.rel_path,
        "uploaded_at": asset.created_at.isoformat() if asset.created_at else None,
    }


async def replace_chunks(
    session: AsyncSession, asset: KnowledgeAsset, normalized: str
) -> list[KnowledgeChunk]:
    """US-210/US-211: normalize, chunk, persist (replacing prior version).

    Returns the created rows so the embedding step (T-S2-6) can fill the
    vectors in place.
    """
    await session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.asset_id == asset.id,
            KnowledgeChunk.organization_id == asset.organization_id,  # ADR-024
        )
    )
    chunks = chunk_text(normalized)
    now = datetime.now(UTC)
    rows: list[KnowledgeChunk] = []
    for index, content in enumerate(chunks):
        row = KnowledgeChunk(
            organization_id=asset.organization_id,
            asset_id=asset.id,
            asset_version=asset.version,
            chunk_index=index,
            content=content,
            char_count=len(content),
            created_at=now,
        )
        session.add(row)
        rows.append(row)
    return rows


async def current_chunks(session: AsyncSession, asset: KnowledgeAsset) -> list[KnowledgeChunk]:
    """Chunks already stored for this asset's CURRENT version, in order.

    Scoped by organization_id as every other chunk query is (ADR-024). An asset
    whose version changed has no rows here, which is exactly the signal that the
    document must be chunked again.
    """
    result = await session.execute(
        select(KnowledgeChunk)
        .where(
            KnowledgeChunk.asset_id == asset.id,
            KnowledgeChunk.organization_id == asset.organization_id,
            KnowledgeChunk.asset_version == asset.version,
        )
        .order_by(KnowledgeChunk.chunk_index)
    )
    return list(result.scalars().all())


async def ensure_chunks(
    session: AsyncSession, asset: KnowledgeAsset, normalized: str
) -> list[KnowledgeChunk]:
    """This version's chunks, chunked only if they are not already the right ones.

    Two code paths index the same document: the worker draining the queue, and
    POST /knowledge-assets/{id}/classify. Both called replace_chunks, which
    deletes every chunk of the asset and re-inserts it, and then embedded all of
    them again - so a file that had already been indexed was re-indexed from
    scratch by whoever arrived second, paying the document's full inference cost
    a second time and competing with the first for the same two inference slots.
    Measured on staging 2026-09-15 as classify calls timing out at 125 s in the
    live suite while the queue was working on the same files.

    The comparison is exact rather than a stored fingerprint: chunk_text is pure
    string slicing, so recomputing it costs no inference, and comparing it to the
    stored contents means a changed document, a changed chunk size, or a changed
    overlap all force a real rebuild instead of silently keeping stale chunks.
    """
    rows = await current_chunks(session, asset)
    expected = chunk_text(normalized)
    if rows and len(rows) == len(expected) and all(
        row.content == content for row, content in zip(rows, expected, strict=True)
    ):
        return rows
    return await replace_chunks(session, asset, normalized)


async def embed_chunk_rows(
    session: AsyncSession,
    rows: list[KnowledgeChunk],
    batch_size: int | None = None,
    budget_seconds: float | None = None,
) -> int:
    """Fill the embeddings of freshly written chunk rows; returns how many.

    Same sub-batching rule as the worker (one inference batch per call, so the
    shared embedding semaphore is released between groups instead of being held
    for a whole document), used by the on-demand classification path.

    That path wrote the chunks and marked the asset "ready" WITHOUT embedding
    them, so the document list showed a finished file with knowledge units while
    semantic search - which only looks at chunks that carry a vector - could not
    see a single one of them. The user saw a ready document and an answer that
    said no document existed.
    """
    # Only the rows that still lack a vector. A document that is already
    # embedded costs nothing here, which is what makes calling this twice - once
    # from the worker, once from classify - cheap instead of a full re-embed.
    pending = [row for row in rows if row.embedding is None]
    if not pending:
        return 0
    from backend.knowledge.embeddings import embed_texts_background

    size = batch_size or get_settings().local_inference_batch_size
    batch = max(1, size)
    done = 0
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    for start in range(0, len(pending), batch):
        # Stop between batches, never mid-batch, so a batch is never half
        # embedded. The overshoot is one batch at worst (~5 s at the measured
        # rate), which is what keeps this a bound rather than a guess: the rows
        # left without a vector are simply picked up by the next caller, and
        # because they are already stored and chunked, that caller embeds only
        # the gaps.
        if deadline is not None and time.monotonic() >= deadline:
            break
        window = pending[start : start + batch]
        vectors = await embed_texts_background([row.content for row in window])
        for row, vector in zip(window, vectors, strict=True):
            row.embedding = vector  # type: ignore[assignment]
            done += 1
        # Commit per batch, exactly as the worker does. This path runs inside the
        # request that asked for the classification, and it used to hold one
        # transaction for the whole document: replace_chunks' row locks plus
        # every embedding the inference slot had not produced yet. A large
        # document made that a multi-minute open transaction, and because every
        # authenticated request refreshes its own sessions row, other users
        # queued behind it - measured on staging 2026-09-15 as four classify
        # calls timing out at 125 s in the live suite. Per-batch commits also
        # mean the vectors already computed survive a restart.
        await session.commit()
    return done


async def list_chunks(session: AsyncSession, organization_id, asset: KnowledgeAsset) -> list[dict]:
    """Chunks of the asset's current version (tenant-isolated)."""
    rows = (
        (
            await session.execute(
                select(KnowledgeChunk)
                .where(
                    KnowledgeChunk.asset_id == asset.id,
                    KnowledgeChunk.organization_id == organization_id,
                    KnowledgeChunk.asset_version == asset.version,
                )
                .order_by(KnowledgeChunk.chunk_index.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "chunk_index": row.chunk_index,
            "content": row.content,
            "char_count": row.char_count,
            "asset_version": row.asset_version,
        }
        for row in rows
    ]
