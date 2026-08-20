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


# ---------------------------------------------------------------- list/filter/sort
#
# S1-18: pagination contract for GET /documents. Only an explicit allowlist of
# columns is sortable (client input is never interpolated into SQL), and both
# `status` and `filter` are scalar, parameterised predicates (no free-text SQL).

SORTABLE_COLUMNS: dict[str, object] = {
    "createdAt": Document.created_at,
    "filename": Document.filename,
    "sizeBytes": Document.size_bytes,
    "status": Document.status,
    "format": Document.format,
}

DEFAULT_SORT = "-createdAt"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _parse_sort(raw: str) -> tuple[object, bool]:
    """Parse ``sort`` into ``(column, descending)``, defaulting to recency.

    Format: ``field`` (ascending) or ``-field`` (descending). Unknown fields fall
    back to the default so a malformed client can never error the request.
    """
    descending = raw.startswith("-")
    key = raw[1:] if descending else raw
    column = SORTABLE_COLUMNS.get(key)
    if column is None:
        return SORTABLE_COLUMNS["createdAt"], True
    return column, descending


async def _count_documents(
    session: AsyncSession, org_id: UUID, status: str | None, query: str | None
) -> int:
    stmt = select(func.count()).where(Document.organization_id == org_id)
    if status:
        stmt = stmt.where(Document.status == status)
    if query:
        stmt = stmt.where(Document.filename.ilike(f"%{query}%"))
    return (await session.execute(stmt)).scalar_one()


async def list_documents(
    session: AsyncSession,
    org: Organization,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = DEFAULT_SORT,
    status_filter: str | None = None,
    query: str | None = None,
) -> schemas.DocumentPage:
    """List an org's documents with pagination, sorting and filtering (S1-18).

    Returns an envelope ``{items, meta}`` where ``meta.total`` is the count of
    matching documents BEFORE paging. ``status_filter`` narrows to one ingestion
    status; ``query`` is a case-insensitive substring match on ``filename``.
    """
    column, descending = _parse_sort(sort)
    order = column.desc() if descending else column.asc()

    total = await _count_documents(session, org.id, status_filter, query)

    stmt = select(Document).where(Document.organization_id == org.id)
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    if query:
        stmt = stmt.where(Document.filename.ilike(f"%{query}%"))
    stmt = stmt.order_by(order, Document.id).offset((page - 1) * page_size).limit(page_size)

    rows = (await session.execute(stmt)).scalars().all()

    total_pages = -(-total // page_size) if total else 0
    return schemas.DocumentPage(
        items=[_document_schema(d) for d in rows],
        meta=schemas.PageMeta(
            total=total,
            page=page,
            pageSize=page_size,
            totalPages=total_pages,
        ),
    )


async def get_document_status(
    session: AsyncSession, org: Organization, doc_id: UUID
) -> schemas.DocumentStatusResponse:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.organization_id != org.id:
        raise NotFoundError("document not found")
    return schemas.DocumentStatusResponse(id=doc.id, status=doc.status, error=doc.error)


async def process_job(job_id) -> None:
    """WAVEB seam: delegate to the loop-safe background worker.

    WAVE-3A left a stub; WAVE-3B implements the real chunk -> embed -> index
    pipeline in ``app.services.ingestion_worker``.
    """
    from app.services import ingestion_worker

    ingestion_worker.process_job(job_id)
