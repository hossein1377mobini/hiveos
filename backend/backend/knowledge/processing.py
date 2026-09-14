"""Minimal processing queue + orchestration (US-203/US-214, T-S2-3).

The scanner (and direct upload) enqueue one job per (asset, version, type);
the partial unique index is the FR-003 dedup rule. Real processing workers
(classify/extract/OCR) land with T-S2-4 - this module owns the state
machine, cancel/retry, and the read API until then.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.models import KnowledgeAsset, Organization, ProcessingJob
from backend.models.processing_job import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    JOB_PRIORITIES,
)

# E: retry ceiling for a failed extraction/embedding job.
MAX_JOB_ATTEMPTS = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _payload(job: ProcessingJob) -> dict:
    return {
        "id": job.id,
        "asset_id": job.asset_id,
        "job_type": job.job_type,
        "priority": job.priority,
        "status": job.status,
        "asset_version": job.asset_version,
        "attempt_count": job.attempt_count,
        "error_detail": job.error_detail,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


async def enqueue_job(
    session: AsyncSession,
    organization_id,
    asset: KnowledgeAsset,
    job_type: str,
    priority: str = "normal",
) -> ProcessingJob | None:
    """US-203 FR-001..FR-006: create + queue one job; None on dedup (FR-003).

    The partial unique index over active statuses is the hard guarantee; the
    pre-check keeps the normal path free of IntegrityErrors.
    """
    if job_type not in ("create", "reprocess"):
        raise ValueError(f"unknown job type: {job_type}")
    existing = (
        await session.execute(
            select(ProcessingJob).where(
                ProcessingJob.asset_id == asset.id,
                ProcessingJob.asset_version == asset.version,
                ProcessingJob.job_type == job_type,
                ProcessingJob.status.in_(ACTIVE_STATUSES),
            )
        )
    # E: scalar_one_or_none() raised MultipleResultsFound inside drain_queue when
    # a race left two active rows, aborting every job behind it in the batch.
    ).scalars().first()
    if existing is not None:
        return None

    job = ProcessingJob(
        organization_id=organization_id,
        asset_id=asset.id,
        job_type=job_type,
        priority=JOB_PRIORITIES[priority],
        status="queued",
        asset_version=asset.version,
    )
    session.add(job)
    await session.flush()
    await record_audit(
        session,
        "processing-job.created",
        organization_id=organization_id,
        entity_type="processing_job",
        entity_id=job.id,
        detail={"asset_id": str(asset.id), "job_type": job_type, "priority": priority},
    )
    await record_audit(
        session,
        "processing-job.queued",
        organization_id=organization_id,
        entity_type="processing_job",
        entity_id=job.id,
    )
    return job


async def get_job(session: AsyncSession, organization: Organization, job_id) -> dict:
    """US-203 API: GET /processing/jobs/{id} - org-isolated (ADR-024)."""
    job = await session.get(ProcessingJob, job_id)
    if job is None or job.organization_id != organization.id:
        raise ApiError(404, "PROCESSING_JOB_NOT_FOUND", "Processing job not found.")
    return _payload(job)


async def list_jobs(session: AsyncSession, organization: Organization, limit: int = 50) -> list[dict]:
    """US-203: the caller's most recent jobs (tenant-isolated)."""
    rows = (
        (
            await session.execute(
                select(ProcessingJob)
                .where(ProcessingJob.organization_id == organization.id)
                .order_by(ProcessingJob.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_payload(row) for row in rows]


async def retry_job(session: AsyncSession, organization: Organization, job_id) -> dict:
    """US-203 FR-008 / scenario 4: failed jobs can be retried."""
    job = await session.get(ProcessingJob, job_id)
    if job is None or job.organization_id != organization.id:
        raise ApiError(404, "PROCESSING_JOB_NOT_FOUND", "Processing job not found.")
    if job.status != "failed":
        raise ApiError(409, "JOB_NOT_RETRYABLE", "Only failed jobs can be retried.")
    # E: the counter was incremented but never checked, so a client could retry
    # the same extraction + embedding forever.
    if job.attempt_count >= MAX_JOB_ATTEMPTS:
        raise ApiError(
            409, "JOB_ATTEMPTS_EXHAUSTED", "This job failed too many times; re-upload the document."
        )
    job.status = "retrying"
    job.attempt_count += 1
    job.error_detail = None
    # E: leave the asset queued so the UI stops showing it as permanently failed
    # for the whole re-run.
    asset = await session.get(KnowledgeAsset, job.asset_id)
    if asset is not None:
        asset.status = "queued"
    await record_audit(
        session,
        "processing-job.retry.requested",
        organization_id=organization.id,
        entity_type="processing_job",
        entity_id=job.id,
        detail={"attempt": job.attempt_count},
    )
    # E: the asset write above forces a flush on the next query, which expires
    # the server-generated updated_at - reading it afterwards lazily loaded it
    # from sync context and answered 500 (MissingGreenlet). Reload it inside the
    # coroutine instead.
    await session.flush()
    await session.refresh(job, attribute_names=["updated_at"])
    return _payload(job)


async def cancel_job(session: AsyncSession, organization: Organization, job_id) -> dict:
    """US-214 (T-S2-3 scope): cancel a queued/pending/retrying job."""
    job = await session.get(ProcessingJob, job_id)
    if job is None or job.organization_id != organization.id:
        raise ApiError(404, "PROCESSING_JOB_NOT_FOUND", "Processing job not found.")
    if job.status not in CANCELLABLE_STATUSES:
        raise ApiError(
            409, "JOB_NOT_CANCELLABLE", f"A job in status '{job.status}' cannot be cancelled."
        )
    job.status = "cancelled"
    await record_audit(
        session,
        "processing-job.cancelled",
        organization_id=organization.id,
        entity_type="processing_job",
        entity_id=job.id,
    )
    return _payload(job)


async def count_active_jobs(session: AsyncSession, organization_id) -> int:
    """Small helper for onboarding-status/dashboard consumers."""
    rows = await session.execute(
        select(ProcessingJob.id).where(
            ProcessingJob.organization_id == organization_id,
            ProcessingJob.status.in_(ACTIVE_STATUSES),
        )
    )
    return len(rows.scalars().all())
