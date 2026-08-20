"""WAVE-3B: background worker that consumes pending ingest jobs.

Loop-safe design (matches ``folder_watcher``): each unit of work creates a
SHORT-LIVED async engine inside ``asyncio.run`` so the worker thread never
shares the request loop's engine (asyncpg connections are event-loop-bound).

Seam: ``process_job(job_id)`` runs the real chunk -> embed -> index pipeline for
one ``ProcessingJob`` and drives the ``Document`` + ``Job`` status lifecycle
(detected/processing -> ready|failed; pending -> running -> succeeded|failed,
honoring ``attempts`` for retry).
"""

import asyncio
import contextlib
import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models import (
    AuditLog,
    Document,
    DocumentChunk,
    IngestionFolderConfig,
    ProcessingJob,
)
from app.services import ingestion_pipeline

_WORKER: "JobWorker" | None = None
_WORKER_LOCK = threading.Lock()


async def _process_one(job_id: UUID, settings, engine) -> None:
    """Real pipeline for a single job (success or failed state — always settles)."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is None or job.status == "succeeded":
            return  # gone or already owned by another worker slot
        doc = await session.get(Document, job.document_id)

        job.status = "running"
        job.attempts = (job.attempts or 0) + 1
        job.updated_at = datetime.now(UTC)
        if doc is not None:
            doc.status = "processing"
            doc.updated_at = datetime.now(UTC)
        await session.commit()

        # ---- the real pipeline (chunk -> embed -> index) ----
        try:
            cfg = (
                await session.execute(
                    select(IngestionFolderConfig).where(
                        IngestionFolderConfig.organization_id == job.organization_id
                    )
                )
            ).scalar_one_or_none()
            if cfg is None:
                raise RuntimeError("no ingestion folder configured for this organization")

            if doc is None:
                raise RuntimeError("document row missing")
            if doc.brain_id is None:
                # US-005 precondition: DocumentChunk.brain_id is NOT NULL; the
                # org's Brain (and workspace) must be initialized before ingest.
                raise RuntimeError(
                    "organization brain not initialized — run US-005 before ingestion"
                )

            # ``doc.filename`` stores the folder-root-relative path (S1-03), so join
            # it directly; basename() would flatten subfolders and break them.
            file_path = os.path.join(cfg.folder_path, doc.filename)
            text = ingestion_pipeline.read_document_text(file_path, doc.format)
            chunk_cfg = ingestion_pipeline.default_chunk_config()
            chunks = ingestion_pipeline.chunk_text(
                text, chunk_size=chunk_cfg["chunk_size"], overlap=chunk_cfg["overlap"]
            )
            vectors = ingestion_pipeline.embed_texts(chunks)

            session.add_all(
                DocumentChunk(
                    tenant_id=doc.tenant_id,
                    organization_id=doc.organization_id,
                    brain_id=doc.brain_id,
                    source_document_id=str(doc.id),  # column is String(64)
                    content=chunk,
                    embedding=vec,
                    chunk_metadata={
                        "format": doc.format, "chunk_size": chunk_cfg["chunk_size"]
                    },
                )
                for chunk, vec in zip(chunks, vectors, strict=True)
            )

            doc.status = "ready"
            doc.error = None
            doc.updated_at = datetime.now(UTC)
            job.status = "succeeded"
            job.last_error = None
            job.updated_at = datetime.now(UTC)
            session.add(
                AuditLog(
                    tenant_id=doc.tenant_id,
                    action="document.ready",
                    payload={
                        "organization_id": str(doc.organization_id),
                        "document_id": str(doc.id),
                        "chunks": len(chunks),
                        "dim": len(vectors[0]) if vectors else 0,
                    },
                )
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — per-file failure stays isolated (FR-008)
            await session.rollback()
            try:
                async with session.begin():
                    job2 = await session.get(ProcessingJob, job_id)
                    doc2 = await session.get(Document, job2.document_id) if job2 else None
                    if doc2 is not None:
                        doc2.status = "failed"
                        doc2.error = str(exc)
                        doc2.updated_at = datetime.now(UTC)
                    if job2 is not None:
                        job2.status = "failed"
                        job2.last_error = str(exc)
                        job2.updated_at = datetime.now(UTC)
                        session.add(
                            AuditLog(
                                tenant_id=job2.tenant_id,
                                action="document.processing.failed",
                                payload={
                                    "organization_id": str(job2.organization_id),
                                    "document_id": str(job.document_id),
                                    "error": str(exc),
                                    "attempts": job2.attempts,
                                },
                            )
                        )
            except Exception:  # noqa: BLE001 — best effort; never mask the pipeline error
                await session.rollback()


_INGEST_ENGINE = None
_INGEST_ENGINE_LOCK = threading.Lock()


def _worker_engine():
    """Reuse ONE null-pool async engine across jobs (no per-call create/dispose).

    ``NullPool`` means every ``connect()`` — on whichever event loop drives the
    job — opens a fresh asyncpg connection that is closed on release, so the
    shared engine is loop-safe even though ``process_job`` spins a fresh
    ``asyncio.run`` loop per unit of work. This removes the S1-07 pool churn of
    ``create_async_engine(...).dispose()`` per job.
    """
    global _INGEST_ENGINE
    with _INGEST_ENGINE_LOCK:
        if _INGEST_ENGINE is None:
            _INGEST_ENGINE = create_async_engine(
                get_settings().database_url, poolclass=NullPool
            )
        return _INGEST_ENGINE


def process_job(job_id: UUID) -> None:
    """Synchronous entry point for one job (loop-safe, callable from any thread)."""
    engine = _worker_engine()

    async def _run():
        await _process_one(job_id, get_settings(), engine)

    asyncio.run(_run())


def _claim_pending_ids(engine) -> list[UUID]:
    """Atomically claim pending jobs (and reclaim stale 'running' ones).

    One worker slot reserves each job via ``UPDATE ... WHERE status='pending'
    RETURNING id`` (committed), so concurrent worker slots never process the same
    job twice. Jobs stuck in ``running`` beyond ``ingestion_job_stale_seconds``
    are treated as abandoned by a crashed worker and reset to ``pending`` for
    retry (crash recovery).
    """
    container: list[UUID] = []

    async def _claim():
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            settings = get_settings()
            now = datetime.now(UTC)
            await session.execute(
                ProcessingJob.__table__.update()
                .where(
                    ProcessingJob.status == "running",
                    ProcessingJob.updated_at
                    < now - timedelta(seconds=settings.ingestion_job_stale_seconds),
                )
                .values(status="pending", last_error="reclaimed after worker stall")
            )
            ids = (
                await session.execute(
                    ProcessingJob.__table__.update()
                    .where(ProcessingJob.status == "pending")
                    .values(status="running", updated_at=now)
                    .returning(ProcessingJob.id)
                )
            ).scalars().all()
            container.extend(ids)
            await session.commit()

    asyncio.run(_claim())
    return container


def process_pending_jobs() -> int:
    """Process all currently-pending jobs. Returns how many were attempted."""
    ids = _claim_pending_ids(_worker_engine())
    for jid in ids:
        process_job(jid)
    return len(ids)


class JobWorker(threading.Thread):
    """Daemon loop that periodically drains the pending ingest queue."""

    def __init__(self, interval: float = 0.0) -> None:
        super().__init__(daemon=True, name="ingestion-job-worker")
        self.interval = interval or get_settings().ingestion_worker_poll_seconds
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            with contextlib.suppress(Exception):  # keep the worker alive on transient errors
                process_pending_jobs()

    def stop(self) -> None:
        self._stop.set()


def start_worker() -> JobWorker:
    """Start (idempotent) the single background job worker."""
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return _WORKER
        _WORKER = JobWorker()
        _WORKER.start()
        return _WORKER


def stop_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        w = _WORKER
        _WORKER = None
    if w is not None:
        w.stop()
        w.join(timeout=1.0)
