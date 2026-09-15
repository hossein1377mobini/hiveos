"""Minimal processing worker (US-203/US-205/US-206, T-S2-4).

Drains queued jobs: classify (magic bytes) -> extract -> store text -> mark
the asset 'ready'. Failures mark the job 'failed' with a clear error code
(US-203 scenario 4) and the asset 'failed'; review-queue types complete
with an empty text and an explicit pipeline (never silently swallowed).
The scheduler loop drains after its scans; tests call the functions
directly.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.knowledge.chunking import build_metadata, normalize_text, replace_chunks
from backend.knowledge.classify import classify_asset, extract_text
from backend.knowledge.embeddings import embed_texts
from backend.models import KnowledgeAsset, KnowledgeSource, ProcessingJob

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _source_path(session: AsyncSession, asset: KnowledgeAsset) -> str | None:
    if asset.source_id is None:
        return None
    source = await session.get(KnowledgeSource, asset.source_id)
    return source.path if source else None


async def process_job(session: AsyncSession, job: ProcessingJob) -> str:
    """Run one queued job end-to-end; returns the final status string."""
    asset = await session.get(KnowledgeAsset, job.asset_id)
    if asset is None:
        job.status = "failed"
        job.error_detail = "asset vanished"
        return "failed"

    job.status = "processing"
    await record_audit(
        session,
        "processing-job.started",
        organization_id=job.organization_id,
        entity_type="processing_job",
        entity_id=job.id,
    )
    # US-1203 AC7 analogue (T-S2-7): zero-credit orgs queue new assets as
    # needs_review until the wallet lands (T-S3-7). Off by default in v0.1.
    if get_settings().zero_credit_review_mode:
        job.status = "completed"
        asset.status = "queued"
        await record_audit(
            session,
            "processing-job.completed",
            organization_id=job.organization_id,
            entity_type="processing_job",
            entity_id=job.id,
            detail={"needs_review": True, "reason": "ZERO_CREDIT"},
        )
        return "completed"
    try:
        folder = await _source_path(session, asset)
        # E: classify/extract are synchronous file IO (open/zip/pypdf/openpyxl/
        # tesseract). Awaiting them directly froze the whole API process - health
        # checks and SSE streams included - for the duration of a large file.
        verdict = await asyncio.to_thread(classify_asset, asset, folder)
        try:
            asset.extracted_text = await asyncio.to_thread(extract_text, asset, folder)
            normalized = normalize_text(asset.extracted_text or "")
            if not normalized and verdict["pipeline"] == "ocr":
                # An image with no legible text - a photo, a logo, a blank or
                # blurred scan - is not a successfully indexed document. It was
                # marked ready like any other asset, so the document table showed
                # a finished row for something that contributed nothing to search
                # and the operator had no reason to look at it.
                job.status = "completed"
                asset.status = "queued"
                await record_audit(
                    session,
                    "processing-job.completed",
                    organization_id=job.organization_id,
                    entity_type="processing_job",
                    entity_id=job.id,
                    detail={"needs_review": True, "pipeline": verdict["pipeline"],
                            "reason": "OCR_EMPTY"},
                )
                return "completed"
            asset.extracted_text = normalized
            asset.asset_metadata = build_metadata(asset)
            chunk_rows = await replace_chunks(session, asset, normalized)
            if chunk_rows:
                # Embed in bounded sub-batches and commit each one, so a large
                # document releases the inference semaphore between batches
                # instead of holding it for the whole file. A search request
                # that arrives mid-document then waits for one batch (seconds)
                # rather than for the file (tens of minutes), and the chunks
                # already embedded survive a crash or restart.
                # One inference batch per commit, NOT a multiple of it. The
                # semaphore is held for the whole embed_texts call, so a larger
                # sub-batch directly becomes the worst-case wait for a search
                # request that arrives mid-document. At the measured ~0.7 s per
                # chunk, 8 chunks is ~5 s of hold; 32 would be ~22 s, which is
                # the same starvation this change exists to remove.
                batch = max(1, get_settings().local_inference_batch_size)
                for start in range(0, len(chunk_rows), batch):
                    window = chunk_rows[start : start + batch]
                    vectors = await embed_texts([row.content for row in window])
                    for row, vector in zip(window, vectors, strict=True):
                        row.embedding = vector  # type: ignore[assignment]
                    await session.commit()
            if len(chunk_rows) >= get_settings().knowledge_max_chunks_per_document:
                # The cap truncated this document. Record it on the asset so the
                # operator can see the file was indexed only in part, rather
                # than silently searching a subset.
                asset.asset_metadata = {
                    **(asset.asset_metadata or {}),
                    "chunks_truncated": True,
                    "chunks_indexed": len(chunk_rows),
                    "chunk_cap": get_settings().knowledge_max_chunks_per_document,
                }
            asset.status = "ready"
        except ApiError as exc:
            if exc.code in ("REVIEW_QUEUE", "OCR_UNAVAILABLE"):
                # US-205: archive/unknown completes as "flagged for review";
                # OCR_UNAVAILABLE keeps the job open for an OCR-capable host.
                job.status = "completed"
                asset.status = "queued"
                await record_audit(
                    session,
                    "processing-job.completed",
                    organization_id=job.organization_id,
                    entity_type="processing_job",
                    entity_id=job.id,
                    detail={"needs_review": True, "pipeline": verdict["pipeline"], "reason": exc.code},
                )
                return "completed"
            raise
        job.status = "completed"
        await record_audit(
            session,
            "processing-job.completed",
            organization_id=job.organization_id,
            entity_type="processing_job",
            entity_id=job.id,
            detail={"asset_type": verdict["asset_type"], "pipeline": verdict["pipeline"]},
        )
    except Exception as exc:  # noqa: BLE001 - job failure must be recorded, not raised
        job.status = "failed"
        code = getattr(exc, "code", "EXTRACTION_FAILED")
        job.error_detail = f"{code}: {exc}"
        asset.status = "failed"
        await record_audit(
            session,
            "processing-job.failed",
            organization_id=job.organization_id,
            entity_type="processing_job",
            entity_id=job.id,
            detail={"error": code},
        )
    return job.status


async def drain_queue(session: AsyncSession, limit: int = 20) -> int:
    """Process up to limit queued jobs (highest priority, oldest first)."""
    rows = (
        (
            await session.execute(
                select(ProcessingJob)
                .where(ProcessingJob.status.in_(("queued", "retrying")))
                .order_by(ProcessingJob.priority.desc(), ProcessingJob.created_at.asc())
                # E: SKIP LOCKED so a scheduler tick and a manual scan (or a
                # second process) never extract and embed the same asset twice.
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    processed = 0
    for job in rows:
        # The row was locked when selected, but re-check the state: it may have
        # been cancelled or completed after the SELECT ordered it.
        if job.status not in ("queued", "retrying"):
            continue
        await process_job(session, job)
        # Commit per job, not once per batch. Each job is a complete unit of
        # work (extract -> chunk -> embed -> status); holding all 20 in one
        # transaction meant no progress was durable until the last one
        # finished, so an operator watching a stuck queue saw a frozen
        # "queued" count with no way to tell slow from hung, and the row locks
        # from with_for_update were held across every embedding batch.
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("failed to commit job %s", job.id)
            continue
        processed += 1
    return processed
