"""US-007 ingestion-folder API logic (WAVE-3A) — transactional use-cases.

Builds the docs surface ON the US-005 Organization Brain substrate but does NOT do
real chunk/embed/index (that is WAVE-3B). This wave provides the ingest pipeline
seam/stub so the API returns live statuses end-to-end.

Security: a configured folder must be absolute, exist on disk, be readable by the
server process, AND resolve (via realpath) to somewhere inside the configured
``ingestion_allowed_roots`` — blocking path traversal outside the allowed set.
"""

import os
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.config import get_settings
from app.errors import ApiError, ConflictError, ForbiddenError, NotFoundError
from app.models import (
    AuditLog,
    Document,
    IngestionFolderConfig,
    Organization,
    ProcessingJob,
)
from app.services import folder_watcher


def _resolve_folder_path(raw: str) -> str:
    """Validate + normalize a caller-supplied folder path.

    Error mapping (documented decision):
    - empty / not absolute  -> 400 (bad_request)
    - does not exist        -> 400 (bad_request)   [a fixable client mistake]
    - exists but unreadable -> 403 (forbidden)     [an access/authorization problem]
    - outside allowed roots -> 403 (forbidden)     [path traversal]
    """
    path = (raw or "").strip()
    if not path:
        raise ApiError("folder path must not be empty")
    if not os.path.isabs(path):
        raise ApiError("folder path must be absolute")

    if not os.path.isdir(path):
        raise ApiError("folder path does not exist")

    # NOTE: os.access R_OK is advisory on Windows (coarse ACLs); the allowed-roots
    # check below is the real isolation boundary.
    if not os.access(path, os.R_OK):
        raise ForbiddenError("no read access to folder path")

    real = os.path.realpath(path)
    roots = [os.path.realpath(r) for r in get_settings().ingestion_allowed_roots]
    norm = os.path.normcase(real)
    allowed = any(
        norm == os.path.normcase(root) or norm.startswith(os.path.normcase(root) + os.sep)
        for root in roots
    )
    if not allowed:
        raise ForbiddenError("folder path is outside the allowed ingestion roots")
    return real


async def _count_by_status(session: AsyncSession, org_id: UUID) -> schemas.IngestionFolderCounts:
    counts = {"detected": 0, "processing": 0, "ready": 0, "failed": 0}
    rows = (
        await session.execute(
            select(Document.status, func.count())
            .where(Document.organization_id == org_id)
            .group_by(Document.status)
        )
    ).all()
    for status, cnt in rows:
        counts[status] = cnt
    return schemas.IngestionFolderCounts(**counts)


def _document_schema(doc: Document) -> schemas.Document:
    return schemas.Document(
        id=doc.id,
        filename=doc.filename,
        format=doc.format,
        sizeBytes=doc.size_bytes,
        status=doc.status,
        error=doc.error,
        createdAt=doc.created_at,
    )


async def configure_ingestion_folder(
    session: AsyncSession, org: Organization, folder_path: str
) -> schemas.IngestionFolderStatus:
    """Configure / re-configure the org's ingestion folder and (re)start its watcher.

    Guards: org must be active; AI model must be configured (FR-010) — both 409.
    Path security per ``_resolve_folder_path`` (400/403). On success upserts the
    one-per-org config, audit-logs, commits, and starts a non-blocking watcher.
    """
    if org.status != "active":
        raise ConflictError("organization is not active")

    # FR-010: block watch activation when the AI model config is incomplete/invalid.
    if not (org.ai_provider or "").strip():
        raise ConflictError("AI model not configured — configure it first")

    resolved = _resolve_folder_path(folder_path)

    org_id = org.id
    tenant_id = org.tenant_id
    now = datetime.now(UTC)

    existing = (
        await session.execute(
            select(IngestionFolderConfig).where(
                IngestionFolderConfig.organization_id == org_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.folder_path = resolved
        existing.active = True
        existing.watch_started_at = now
    else:
        session.add(
            IngestionFolderConfig(
                tenant_id=tenant_id,
                organization_id=org_id,
                folder_path=resolved,
                active=True,
                watch_started_at=now,
            )
        )

    session.add(
        AuditLog(
            tenant_id=tenant_id,
            action="ingestion_folder.configured",
            actor_ref=None,
            payload={
                "organization_id": str(org_id),
                "folder_path": resolved,
            },
        )
    )
    await session.commit()

    # Non-blocking: start (or idempotently reuse) the per-org watcher.
    folder_watcher.start_watcher(org_id, resolved)

    counts = await _count_by_status(session, org_id)
    return schemas.IngestionFolderStatus(
        active=True,
        folderPath=resolved,
        watchStartedAt=now,
        counts=counts,
    )


async def get_ingestion_status(
    session: AsyncSession, org: Organization
) -> schemas.IngestionFolderStatus:
    cfg = (
        await session.execute(
            select(IngestionFolderConfig).where(
                IngestionFolderConfig.organization_id == org.id
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise NotFoundError("ingestion folder not configured")

    counts = await _count_by_status(session, org.id)
    return schemas.IngestionFolderStatus(
        active=cfg.active,
        folderPath=cfg.folder_path,
        watchStartedAt=cfg.watch_started_at,
        counts=counts,
    )


async def list_documents(
    session: AsyncSession, org: Organization
) -> list[schemas.Document]:
    rows = (
        await session.execute(
            select(Document)
            .where(Document.organization_id == org.id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return [_document_schema(d) for d in rows]


async def get_document_status(
    session: AsyncSession, org: Organization, doc_id: UUID
) -> schemas.DocumentStatusResponse:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.organization_id != org.id:
        raise NotFoundError("document not found")
    return schemas.DocumentStatusResponse(id=doc.id, status=doc.status, error=doc.error)


async def process_job(job_id) -> None:
    """WAVE-3B SEAM — consume a pending ingest job (chunk -> embed -> index).

    WAVE-3A has no real pipeline, so this stub transitions the job
    ``pending -> running -> succeeded`` and the document ``detected -> ready`` so the
    full status flow is observable. WAVE-3B replaces the body with the real worker:
    read the file, chunk it, embed via ``org.ai_provider``, write pgvector
    ``DocumentChunk`` rows, then set ``ready`` (or ``failed`` + ``last_error`` on
    exception, honoring ``ProcessingJob.attempts`` for retry).
    """
    from app.db import get_session_factory

    async with get_session_factory()() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is None or job.status in ("succeeded", "running"):
            return

        job.status = "running"
        job.attempts = (job.attempts or 0) + 1
        job.updated_at = datetime.now(UTC)
        await session.commit()

        # TODO(WAVE-3B): real chunk -> embed -> index pipeline goes here.
        doc = await session.get(Document, job.document_id)
        if doc is not None:
            doc.status = "ready"
            doc.error = None
            doc.updated_at = datetime.now(UTC)

        job.status = "succeeded"
        job.last_error = None
        job.updated_at = datetime.now(UTC)
        await session.commit()
