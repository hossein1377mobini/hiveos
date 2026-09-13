"""Direct document upload + source enable/disable (US-201, T-S2-1).

FR-009 (Amendment 2): multipart, multi-file upload of allowed formats
(US-205 list minus HTML) under a configurable per-file size cap
(US-1606). Files land under the server-configured storage root; each file
becomes a queued KnowledgeAsset entering the US-203+ pipeline via the
'knowledge-asset.uploaded' event.

FR-008: a source can be disabled/re-enabled; disabled sources accept no
new queue entries (the scheduler itself is US-202/S2).
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.knowledge.chunking import build_metadata, list_chunks, normalize_text, replace_chunks
from backend.knowledge.classify import classify_asset, extract_text
from backend.knowledge.processing import enqueue_job
from backend.models import KnowledgeAsset, KnowledgeSource, Organization

# US-205 classification table, v0.1 active formats; HTML is explicitly banned.
ALLOWED_EXTENSIONS = frozenset(
    {"txt", "md", "pdf", "docx", "pptx", "xlsx", "csv", "jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"}
)

_SCAN_BLOCKED = ("disabled", "failed")
# US-1606 caps each file; these bound the request itself so one multipart POST
# cannot fill the disk or the worker's memory.
MAX_FILES_PER_UPLOAD = 20
MAX_UPLOAD_REQUEST_MB = 100


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _active_source(session: AsyncSession, organization_id) -> KnowledgeSource | None:
    return (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.organization_id == organization_id)
        )
    ).scalar_one_or_none()


def _validate_file(filename: str, size: int) -> str:
    """US-201 validation rules for one uploaded file; returns the extension."""
    settings = get_settings()
    extension = Path(filename).suffix.lstrip(".").lower()
    if not extension or extension not in ALLOWED_EXTENSIONS:
        raise ApiError(
            400,
            "UPLOAD_FORMAT_NOT_ALLOWED",
            f"File format .{extension or '?'} is not allowed.",
        )
    if filename.lower().endswith((".htm", ".html")):
        raise ApiError(400, "UPLOAD_FORMAT_NOT_ALLOWED", "HTML files are not allowed.")
    max_bytes = settings.upload_max_file_mb * 1024 * 1024
    if size > max_bytes:
        raise ApiError(
            400,
            "UPLOAD_TOO_LARGE",
            f"File exceeds the {settings.upload_max_file_mb}MB limit.",
        )
    return extension


def _storage_dir(organization_id) -> Path:
    path = Path(get_settings().storage_root) / "uploads" / str(organization_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _org_storage_bytes(session: AsyncSession, organization_id) -> int:
    """Total bytes already stored for one organization.

    Counted from the asset rows rather than by walking the directory: the
    filesystem also holds soft-deleted and orphaned files, and a quota must
    measure what the organization actually owns."""
    total = (
        await session.execute(
            select(func.coalesce(func.sum(KnowledgeAsset.size_bytes), 0)).where(
                KnowledgeAsset.organization_id == organization_id,
                KnowledgeAsset.deleted_at.is_(None),
            )
        )
    ).scalar()
    return int(total or 0)


async def _assert_quota(session: AsyncSession, organization, incoming_bytes: int) -> None:
    """FR-011: refuse an upload that would push the organization past its cap.

    Without this, one tenant can fill the shared disk and take every other
    tenant down with it - the failure is silent until the volume is full.
    The admin panel can raise the cap per organization; 0 means unlimited.
    """
    limit_mb = getattr(organization, "storage_quota_mb", None)
    if not limit_mb:
        return
    used = await _org_storage_bytes(session, organization.id)
    limit = int(limit_mb) * 1024 * 1024
    if used + incoming_bytes > limit:
        raise ApiError(
            413,
            "STORAGE_QUOTA_EXCEEDED",
            f"Storage quota of {limit_mb}MB would be exceeded.",
        )


async def upload_assets(
    session: AsyncSession, organization: Organization, user_id, files
) -> dict:
    """US-201 scenario 5: validate, persist, and queue each file."""
    if not files:
        raise ApiError(400, "UPLOAD_EMPTY", "No files were provided.")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise ApiError(
            400,
            "UPLOAD_TOO_MANY_FILES",
            f"At most {MAX_FILES_PER_UPLOAD} files can be uploaded at once.",
        )

    source = await _active_source(session, organization.id)
    if source is not None and source.status in _SCAN_BLOCKED:
        raise ApiError(
            409, "SOURCE_DISABLED", "The knowledge source is disabled; enable it first."
        )

    stored: list[dict] = []
    rejected: list[dict] = []
    upload_dir = _storage_dir(organization.id)

    settings = get_settings()
    per_file_max = settings.upload_max_file_mb * 1024 * 1024
    request_max = MAX_UPLOAD_REQUEST_MB * 1024 * 1024
    total_bytes = 0

    # FR-011: the per-file and per-request caps bound one upload; the quota
    # bounds the whole tenant. Checked before any body is buffered so an
    # over-quota organization never pays for the transfer.
    declared_total = sum(
        int(getattr(f, "size", 0) or 0) for f in files
    )
    await _assert_quota(session, organization, declared_total)

    for upload in files:
        # US-1606: reject on the declared size BEFORE buffering the body — the
        # old order read the whole file into memory and only then measured it.
        declared = getattr(upload, "size", None)
        if declared is not None and declared > per_file_max:
            rejected.append(
                {
                    "name": upload.filename,
                    "code": "UPLOAD_TOO_LARGE",
                    "message": f"File exceeds the {settings.upload_max_file_mb}MB limit.",
                }
            )
            continue
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > request_max:
            raise ApiError(
                400,
                "UPLOAD_TOO_LARGE",
                f"Upload exceeds the {MAX_UPLOAD_REQUEST_MB}MB request limit.",
            )
        try:
            extension = _validate_file(upload.filename or "", len(content))
        except ApiError as exc:
            rejected.append({"name": upload.filename, "code": exc.code, "message": exc.message})
            continue

        asset = KnowledgeAsset(
            organization_id=organization.id,
            source_id=source.id if source is not None else None,
            name=Path(upload.filename).name,
            storage_path="",  # filled after flush - the id is part of the path
            size_bytes=len(content),
            extension=extension,
            status="queued",
            uploaded_by=user_id,
        )
        session.add(asset)
        await session.flush()

        target = upload_dir / f"{asset.id}.{extension}"
        # the write is blocking file IO; keep the event loop free to serve
        # the other requests waiting on this worker.
        await asyncio.to_thread(target.write_bytes, content)
        asset.storage_path = str(target)
        stored.append(
            {
                "id": asset.id,
                "name": asset.name,
                "status": asset.status,
                "size_bytes": asset.size_bytes,
            }
        )
        await record_audit(
            session,
            "knowledge-asset.uploaded",
            organization_id=organization.id,
            actor_user_id=user_id,
            entity_type="knowledge_asset",
            entity_id=asset.id,
            detail={"name": asset.name, "size_bytes": asset.size_bytes},
        )
        # US-201 FR-009: uploads enter the SAME US-203+ pipeline (no side path).
        await enqueue_job(session, organization.id, asset, "create")

    return {"stored": stored, "rejected": rejected}


async def set_source_status(
    session: AsyncSession, organization: Organization, source_id, status: str
) -> dict:
    """US-201 FR-008 / scenario 4: disable or re-enable the single source."""
    if status not in ("active", "disabled"):
        raise ApiError(400, "INVALID_STATUS", "Status must be active or disabled.")
    source = await session.get(KnowledgeSource, source_id)
    if source is None or source.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered.")
    source.status = status
    await record_audit(
        session,
        "knowledge-source.updated",
        organization_id=organization.id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={"status": status},
    )
    return {"id": source.id, "path": source.path, "status": source.status}


async def list_assets(
    session: AsyncSession, organization: Organization, status: str = "active"
) -> list[dict]:
    """US-007 FR-005 + US-241 FR-003: asset list; status=deleted lists tombstones."""
    visible = KnowledgeAsset.deleted_at.is_(None) if status != "deleted" else (
        KnowledgeAsset.deleted_at.is_not(None)
    )
    rows = (
        await session.execute(
            select(KnowledgeAsset)
            .where(
                KnowledgeAsset.organization_id == organization.id,
                visible,
            )
            .order_by(KnowledgeAsset.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "size_bytes": row.size_bytes,
            "extension": row.extension,
            "origin": "upload" if row.source_id is None else "folder_scan",
            "deleted_at": row.deleted_at,
        }
        for row in rows
    ]


async def classify_single_asset(
    session: AsyncSession, organization: Organization, asset_id
) -> dict:
    """US-205 API: classify + extract one asset on demand (GET classification)."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id or asset.deleted_at is not None:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    folder = None
    if asset.source_id is not None:
        source = await session.get(KnowledgeSource, asset.source_id)
        folder = source.path if source else None
    verdict = classify_asset(asset, folder)
    needs_review: str | None = None
    try:
        asset.extracted_text = extract_text(asset, folder)
        normalized = normalize_text(asset.extracted_text or "")
        asset.extracted_text = normalized
        asset.asset_metadata = build_metadata(asset)
        await replace_chunks(session, asset, normalized)
        asset.status = "ready"
    except ApiError as exc:
        if exc.code in ("REVIEW_QUEUE", "OCR_UNAVAILABLE"):
            # US-205: archive/unknown stays queued, explicitly flagged for review;
            # OCR_UNAVAILABLE keeps the asset queued for a later OCR-capable run.
            needs_review = exc.code
        else:
            raise
    await record_audit(
        session,
        "knowledge-asset.classified",
        organization_id=organization.id,
        entity_type="knowledge_asset",
        entity_id=asset.id,
        detail={
            "asset_type": verdict["asset_type"],
            "pipeline": verdict["pipeline"],
            "needs_review": needs_review,
        },
    )
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "pipeline": asset.pipeline,
        "status": asset.status,
        "classified_at": asset.classified_at,
        "text_length": len(asset.extracted_text or ""),
        "needs_review": needs_review is not None,
    }


async def list_asset_chunks(
    session: AsyncSession, organization: Organization, asset_id
) -> dict:
    """US-211 API: chunks of the asset's current version."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id or asset.deleted_at is not None:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    chunks = await list_chunks(session, organization.id, asset)
    return {
        "id": asset.id,
        "asset_version": asset.version,
        "total": len(chunks),
        "chunks": chunks,
    }


async def get_asset_metadata(
    session: AsyncSession, organization: Organization, asset_id
) -> dict:
    """US-208 API: the pipeline metadata bag."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id or asset.deleted_at is not None:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    metadata = asset.asset_metadata or build_metadata(asset)
    return {"id": asset.id, "metadata": metadata}


async def get_classification(
    session: AsyncSession, organization: Organization, asset_id
) -> dict:
    """US-205 API: GET classification of one asset."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id or asset.deleted_at is not None:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "pipeline": asset.pipeline,
        "status": asset.status,
        "classified_at": asset.classified_at,
        "text_length": len(asset.extracted_text or ""),
    }


async def soft_delete_asset(
    session: AsyncSession, organization: Organization, user_id, asset_id
) -> dict:
    """US-241 (v0.1 scope): soft delete an uploaded document by the Owner.

    Validation rules: uploads only (folder documents are owned by the scan,
    US-202/US-216) and idempotent for already-deleted assets. The physical
    file is never touched (retention -> US-216, v0.3).
    """
    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    if asset.rel_path is not None:
        # US-241 scenario 2: folder documents (rel_path set by the scanner,
        # US-202) are not deletable in v0.1 — even when an upload was later
        # linked to a source, only scanner-owned rows carry rel_path.
        raise ApiError(
            409, "FOLDER_ASSET_NOT_DELETABLE", "Folder documents cannot be deleted here."
        )
    if asset.deleted_at is not None:
        return {"id": asset.id, "deleted": True}
    asset.deleted_at = _utc_now()
    await record_audit(
        session,
        "knowledge-asset.deleted",
        organization_id=organization.id,
        actor_user_id=user_id,
        entity_type="knowledge_asset",
        entity_id=asset.id,
    )
    return {"id": asset.id, "deleted": True}