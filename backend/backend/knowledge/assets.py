"""Direct document upload + source enable/disable (US-201, T-S2-1).

FR-009 (Amendment 2): multipart, multi-file upload of allowed formats
(US-205 list minus HTML) under a configurable per-file size cap
(US-1606). Files land under the server-configured storage root; each file
becomes a queued KnowledgeAsset entering the US-203+ pipeline via the
'knowledge-asset.uploaded' event.

FR-008: a source can be disabled/re-enabled; disabled sources accept no
new queue entries (the scheduler itself is US-202/S2).
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.models import KnowledgeAsset, KnowledgeSource, Organization

# US-205 classification table, v0.1 active formats; HTML is explicitly banned.
ALLOWED_EXTENSIONS = frozenset(
    {"txt", "md", "pdf", "docx", "pptx", "xlsx", "csv", "jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"}
)

_SCAN_BLOCKED = ("disabled", "failed")


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


async def upload_assets(
    session: AsyncSession, organization: Organization, user_id, files
) -> dict:
    """US-201 scenario 5: validate, persist, and queue each file."""
    if not files:
        raise ApiError(400, "UPLOAD_EMPTY", "No files were provided.")

    source = await _active_source(session, organization.id)
    if source is not None and source.status in _SCAN_BLOCKED:
        raise ApiError(
            409, "SOURCE_DISABLED", "The knowledge source is disabled; enable it first."
        )

    stored: list[dict] = []
    rejected: list[dict] = []
    upload_dir = _storage_dir(organization.id)

    for upload in files:
        content = await upload.read()
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
        with open(target, "wb") as handle:
            handle.write(content)
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


async def list_assets(session: AsyncSession, organization: Organization) -> list[dict]:
    """US-007 FR-005: the visible asset list with its pipeline status."""
    rows = (
        await session.execute(
            select(KnowledgeAsset)
            .where(
                KnowledgeAsset.organization_id == organization.id,
                KnowledgeAsset.deleted_at.is_(None),
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
        }
        for row in rows
    ]


async def soft_delete_asset(
    session: AsyncSession, organization: Organization, user_id, asset_id
) -> dict:
    """US-241 (v0.1 scope): soft delete an uploaded document by the Owner."""
    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "Asset not found.")
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
