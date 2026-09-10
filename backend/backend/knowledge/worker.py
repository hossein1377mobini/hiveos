"""Minimal processing worker (US-203/US-205/US-206, T-S2-4).

Drains queued jobs: classify (magic bytes) -> extract -> store text -> mark
the asset 'ready'. Failures mark the job 'failed' with a clear error code
(US-203 scenario 4) and the asset 'failed'; review-queue types complete
with an empty text and an explicit pipeline (never silently swallowed).
The scheduler loop drains after its scans; tests call the functions
directly.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.knowledge.chunking import build_metadata, normalize_text, replace_chunks
from backend.knowledge.classify import classify_asset, extract_text
from backend.knowledge.embeddings import embed_texts
from backend.models import KnowledgeAsset, KnowledgeSource, ProcessingJob


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
    try:
        folder = await _source_path(session, asset)
        verdict = classify_asset(asset, folder)
        try:
            asset.extracted_text = extract_text(asset, folder)
            normalized = normalize_text(asset.extracted_text or "")
            asset.extracted_text = normalized
            asset.asset_metadata = build_metadata(asset)
            chunk_rows = await replace_chunks(session, asset, normalized)
            if chunk_rows:
                vectors = embed_texts([row.content for row in chunk_rows])
                for row, vector in zip(chunk_rows, vectors, strict=True):
                    row.embedding = vector  # type: ignore[assignment]
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
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for job in rows:
        await process_job(session, job)
    await session.commit()
    return len(rows)
