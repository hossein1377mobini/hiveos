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

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.knowledge.chunking import build_metadata, list_chunks, normalize_text, replace_chunks
from backend.knowledge.classify import classify_asset, extract_text
from backend.knowledge.processing import enqueue_job
from backend.models import KnowledgeAsset, KnowledgeChunk, KnowledgeSource, Organization

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


def visible_to(user_id, is_admin: bool = False):
    """The one predicate that decides whether a user may read an asset.

    Every read path must apply it: the file list, the metadata and download
    endpoints, the client manifest and semantic search. It is a function rather
    than a literal in one place because the leak it closes came from four
    separate queries each filtering on organization_id alone, so a new read path
    would silently inherit the same hole.

    Org-visible rows (owner_id IS NULL) are the org-level folder's files and rows
    predating migration 0029; everything else belongs to exactly one user. A user
    sees their own files plus the organization's shared ones, never a colleague's.

    is_admin=True is the PO's requirement (2026-09): "we collect the whole
    organization's knowledge, but each person reaches as much of it as their
    access level allows" - and the level above a member is the organization
    Owner, who reaches ALL of it. When is_admin is true there is deliberately NO
    owner filter at all. The organization_id filter is applied by every caller
    and is the tenant boundary (ADR-024); this predicate only ever decides
    between members of the SAME organization.
    """
    if is_admin:
        return text("true")
    if user_id is None:
        return KnowledgeAsset.owner_id.is_(None)
    return (KnowledgeAsset.owner_id == user_id) | KnowledgeAsset.owner_id.is_(None)


async def is_org_admin(session: AsyncSession, organization_id, user_id) -> bool:
    """Whether this user is the organization's Owner (its admin).

    Same definition the auth context uses (organizations.owner_user_id), read
    here because internal callers - the execution cycle, which only has an
    organization_id and a requested_by - have no AuthContext to take it from.
    A second definition would be a second source of truth for "who is admin",
    so both must change together if the concept ever moves.
    """
    if user_id is None:
        return False
    organization = await session.get(Organization, organization_id)
    return organization is not None and organization.owner_user_id == user_id


async def _active_source(
    session: AsyncSession, organization_id, user_id=None
) -> KnowledgeSource | None:
    """The folder that governs this user's uploads.

    Prefers the caller's own folder and falls back to the organization-wide one,
    so a user who registered no folder still lands their uploads in a valid
    source rather than failing. Without the user preference, uploads in a
    multi-member organization would attach to whichever folder happened to sort
    first, which could be a colleague's.

    A user may now register SEVERAL folders (PO request 2026-09), so "one of
    mine" is not unique any more: the earliest-registered one is chosen, in a
    deterministic order, or two concurrent uploads could pick different parents
    for identical requests. Registration order is the tie-break because it is
    the one thing that never changes for a given row without a delete.
    """
    rows = (
        (
            await session.execute(
                select(KnowledgeSource)
                .where(KnowledgeSource.organization_id == organization_id)
                .order_by(KnowledgeSource.created_at, KnowledgeSource.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    for source in rows:
        if user_id is not None and source.user_id == user_id:
            return source
    for source in rows:
        if source.user_id is None:
            return source
    return None


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


# The subfolder the system creates inside a user's folder for files it writes
# itself (generated reports, exports). The PO's rule: system-created files live
# in the same folder as the user's own, separated into a folder named "برنامه"
# so a generated report is never mistaken for something the user uploaded.
SYSTEM_SUBFOLDER = "برنامه"


def _storage_dir(
    organization_id, user_id=None, system: bool = False, source_id=None
) -> Path:
    """Where a file's bytes live on this server.

    <root>/uploads/<org>/<user>/[<source_id>/]["برنامه"/]

    A user may register SEVERAL folders (PO request 2026-09). Each source gets
    its own subfolder, derived from its id, or two folders' files would land in
    one directory and a same-named file in the second folder would either
    collide with or overwrite the first. The id - not the folder path - is the
    key, because a client path is user-supplied text and cannot appear in a
    server-side path.

    Files the system generates still go into the "برنامه" subfolder of the
    requesting user's directory rather than being interleaved with their
    uploads. The source argument is optional so the report path (which has no
    source) keeps its existing layout.

    The path is built from ids only, never from user-supplied text, so a crafted
    filename or title cannot traverse out of the tenant's directory.
    """
    path = Path(get_settings().storage_root) / "uploads" / str(organization_id)
    if user_id is not None:
        path = path / str(user_id)
    if source_id is not None:
        path = path / str(source_id)
    if system:
        path = path / SYSTEM_SUBFOLDER
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

    source = await _active_source(session, organization.id, user_id)
    if source is not None and source.status in _SCAN_BLOCKED:
        raise ApiError(
            409, "SOURCE_DISABLED", "The knowledge source is disabled; enable it first."
        )

    stored: list[dict] = []
    rejected: list[dict] = []
    # The user's own upload: their directory, under the source it attaches to
    # (one subfolder per folder they registered), not the system subfolder.
    upload_dir = _storage_dir(
        organization.id, user_id, source_id=source.id if source is not None else None
    )

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
            # The upload is the user's file, so they own it. Without this the row
            # would be org-visible and every colleague could read it.
            owner_id=user_id,
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
    session: AsyncSession,
    organization: Organization,
    status: str = "active",
    user_id=None,
    is_admin: bool = False,
) -> list[dict]:
    """US-007 FR-005 + US-241 FR-003: asset list; status=deleted lists tombstones.

    Scoped to what the caller may read: their own files plus the organization's
    shared ones, and - for the organization Owner (is_admin) - everything in the
    organization. This filtered on organization_id alone before, so every member
    of an organization saw every other member's uploads.
    """
    visible = KnowledgeAsset.deleted_at.is_(None) if status != "deleted" else (
        KnowledgeAsset.deleted_at.is_not(None)
    )
    rows = (
        await session.execute(
            select(KnowledgeAsset)
            .where(
                KnowledgeAsset.organization_id == organization.id,
                visible,
                visible_to(user_id, is_admin),
            )
            .order_by(KnowledgeAsset.created_at.desc())
        )
    ).scalars().all()
    # H2: the document table had no progress column because this endpoint
    # reported nothing but a coarse status, so "queued" looked identical for a
    # file waiting its turn and one that had been OCR'd but not chunked. The
    # pipeline stage and text length are already on the row - they were simply
    # never read. Reported as-is, not as a percentage: a percentage here would
    # be invented, and an invented progress bar is worse than an honest label.
    chunk_counts = await _chunk_counts(session, organization.id, [row.id for row in rows])
    return [
        {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "size_bytes": row.size_bytes,
            "extension": row.extension,
            "origin": "upload" if row.source_id is None else "folder_scan",
            "deleted_at": row.deleted_at,
            "asset_type": row.asset_type,
            "pipeline": row.pipeline,
            # 0 for a file whose text has not been extracted yet.
            "text_length": len(row.extracted_text or ""),
            "chunks": chunk_counts.get(row.id, 0),
            "classified_at": row.classified_at,
        }
        for row in rows
    ]


async def _chunk_counts(
    session: AsyncSession, organization_id, asset_ids: list
) -> dict:
    """Chunk count per asset, in one query rather than one per row."""
    if not asset_ids:
        return {}
    rows = await session.execute(
        select(KnowledgeChunk.asset_id, func.count())
        .where(
            KnowledgeChunk.organization_id == organization_id,
            KnowledgeChunk.asset_id.in_(asset_ids),
        )
        .group_by(KnowledgeChunk.asset_id)
    )
    return {asset_id: int(count) for asset_id, count in rows.all()}


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


def _readable(asset, organization, user_id, is_admin: bool = False) -> bool:
    """Whether this user may read this asset row.

    Mirrors visible_to() for a row already loaded, so the single-row endpoints
    (metadata, download, classification) enforce exactly what the list query
    enforces. A 404 rather than a 403 is deliberate and is what the callers
    return: telling a user "this exists but is not yours" leaks the existence of
    a colleague's file.

    is_admin is the organization Owner (see visible_to): the PO's access model
    gives them the whole organization's knowledge. It never crosses the
    organization boundary - organization_id is checked first, for everyone.
    """
    if asset is None or asset.organization_id != organization.id:
        return False
    if asset.deleted_at is not None:
        return False
    if is_admin:
        return True
    if asset.owner_id is None:
        return True
    return user_id is not None and asset.owner_id == user_id


async def get_asset_metadata(
    session: AsyncSession, organization: Organization, asset_id, user_id=None, is_admin: bool = False
) -> dict:
    """US-208 API: the pipeline metadata bag."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if not _readable(asset, organization, user_id, is_admin):
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    metadata = asset.asset_metadata or build_metadata(asset)
    return {"id": asset.id, "metadata": metadata}


async def get_asset(
    session: AsyncSession, organization: Organization, asset_id, user_id=None, is_admin: bool = False
) -> KnowledgeAsset | None:
    """Fetch one live asset the caller is allowed to read.

    Returns None rather than raising so the caller decides the status code: the
    download route answers 404 for "no such row" and 404 for "row exists but
    the bytes are gone", and those are different messages to the user.

    Also returns None for a colleague's file. This is the download path, so
    without the ownership check any authenticated member of an organization
    could fetch any other member's document by id.
    """
    asset = await session.get(KnowledgeAsset, asset_id)
    if not _readable(asset, organization, user_id, is_admin):
        return None
    return asset


async def get_classification(
    session: AsyncSession, organization: Organization, asset_id, user_id=None, is_admin: bool = False
) -> dict:
    """US-205 API: GET classification of one asset."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if not _readable(asset, organization, user_id, is_admin):
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
    # Deleting is a write, so it is stricter than reading: org-visible files may
    # be read by everyone but deleted by no one through this path, and a
    # colleague's file is not deletable at all.
    if asset.owner_id is not None and asset.owner_id != user_id:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
    if asset.owner_id is None:
        raise ApiError(
            403, "ASSET_NOT_OWNED", "Only the owner of a document can delete it."
        )
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