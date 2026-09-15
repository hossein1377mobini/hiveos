"""Client-folder knowledge source (US-007, PO decision 2026-09-14).

In the cloud v0.1 delivery the ingestion folder lives on the OWNER'S OWN
machine (ADR-023 thin client): the Windows wrapper opens a real folder picker,
watches that folder, and uploads the files that are new or changed. The server
can never walk that path, so this module owns the two operations that replace
the server-side scanner for such a source:

* register_client_folder - record the folder the owner picked (a label only)
* sync_client_manifest   - reconcile the client's manifest into assets

The reconciliation keeps exactly the US-202 semantics: new files queue,
changed files get a new version and re-enter the queue, files the client no
longer reports are soft-deleted with their history preserved (never a silent
hard delete).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.knowledge.assets import ALLOWED_EXTENSIONS
from backend.knowledge.processing import enqueue_job
from backend.models import (
    KnowledgeAsset,
    KnowledgeSource,
    Organization,
    OrganizationBrain,
)

MAX_MANIFEST_ENTRIES = 5_000
CLIENT_PATH_MAX = 500


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_client_path(path_text: str) -> str:
    """Normalize the folder path reported by the client.

    The path belongs to the owner's machine (usually Windows), so the server
    must NOT apply POSIX absolute-path rules to it - applying them is what made
    every real client folder fail with INGESTION_PATH_NOT_ABSOLUTE.
    """
    text = (path_text or "").strip().strip('"').strip("'")
    if not text:
        raise ApiError(400, "INGESTION_PATH_REQUIRED", "Please choose a folder.")
    text = text.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > CLIENT_PATH_MAX:
        raise ApiError(400, "INGESTION_PATH_TOO_LONG", "The folder path is too long.")
    # 'c:/x' -> 'C:/x': the drive letter is the one part Windows is strict about.
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        text = text[0].upper() + text[1:]
    # Keep a bare drive root ("C:/") intact; every other trailing slash goes.
    if len(text) > 3 and text.endswith("/"):
        text = text.rstrip("/")
    return text


def normalize_rel_path(rel_path: str) -> str | None:
    """Manifest entry -> safe relative path, or None when it must be rejected.

    The manifest comes from the client, so it is untrusted input: absolute
    paths, drive letters and '..' segments must never escape the folder.
    """
    text = (rel_path or "").strip().replace("\\", "/")
    if not text or len(text) > CLIENT_PATH_MAX:
        return None
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _manifest_extension(rel_path: str) -> str:
    name = rel_path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower()[:10] if "." in name else ""


def _is_scannable(rel_path: str) -> bool:
    """Same US-205 format table the server-side scanner enforces."""
    return _manifest_extension(rel_path) in ALLOWED_EXTENSIONS


async def _matching_source(
    session: AsyncSession, organization_id, user_id, path_label: str
) -> KnowledgeSource | None:
    """The caller's already-registered folder with EXACTLY this path, if any.

    Unlike the server-side scanner there is nothing to validate: the path is on
    the owner's machine, so it is compared as a label. Comparing it (instead of
    "the caller's one folder") is what allows several folders per user while
    still making a repeated registration of the same folder idempotent.
    """
    owner_clause = (
        KnowledgeSource.user_id == user_id
        if user_id is not None
        else KnowledgeSource.user_id.is_(None)
    )
    return (
        await session.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.organization_id == organization_id,
                owner_clause,
                KnowledgeSource.path_label == path_label,
            )
        )
    ).scalar_one_or_none()


async def _ready_brain(
    session: AsyncSession, organization: Organization
) -> OrganizationBrain:
    brain = (
        await session.execute(
            select(OrganizationBrain).where(OrganizationBrain.organization_id == organization.id)
        )
    ).scalar_one_or_none()
    if brain is None or brain.status != "ready":
        raise ApiError(
            409, "KNOWLEDGE_BRAIN_NOT_READY", "Complete the previous onboarding steps first."
        )
    return brain


async def register_client_folder(
    session: AsyncSession, organization: Organization, path_text: str, user_id=None
) -> dict:
    """US-007: register the folder this user picked on their own computer.

    PO request 2026-09: a user may define SEVERAL folders, so this CREATES a new
    source for a path that is not already registered by the caller. Only the
    exact same path for the same user is reused (pressing the button twice is
    not a request for two folders). Previously it looked the caller up by
    user_id and overwrote their single folder, which made a second folder
    impossible.

    user_id=None still keeps the organization-wide folder, and there may be
    several of those too.
    """
    brain = await _ready_brain(session, organization)
    label = normalize_client_path(path_text)
    source = await _matching_source(session, organization.id, user_id, label)
    if source is None:
        source = KnowledgeSource(
            organization_id=organization.id,
            user_id=user_id,
            workspace_id=brain.workspace_id,
            brain_id=brain.id,
            source_type="client_folder",
            path=label,
            path_label=label,
        )
        session.add(source)
        await session.flush()
        reused = False
    else:
        # Same folder, same user: update the label in place.
        source.source_type = "client_folder"
        source.path = label
        source.path_label = label
        reused = True
    await record_audit(
        session,
        "knowledge-source.registered",
        organization_id=organization.id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={"path_label": label, "source_type": "client_folder", "reused": reused},
    )
    return {
        "id": source.id,
        "path": label,
        "path_label": label,
        "source_type": "client_folder",
        "status": source.status,
        "scan_interval_minutes": source.scan_interval_minutes,
        "last_scanned_at": source.last_scanned_at,
        "file_state": source.discovered_files,
        "reused": reused,
    }


async def sync_client_manifest(
    session: AsyncSession,
    organization: Organization,
    entries: list[dict],
    source_id=None,
    user_id=None,
) -> dict:
    """Reconcile the client's file manifest into KnowledgeAsset rows.

    source_id is EXPLICIT now (PO request 2026-09: a user may hold several
    folders). The old code took the organization's single source with
    scalar_one_or_none(), which raised MultipleResultsFound the moment a second
    folder existed - and if it had not, it would have reconciled every folder's
    files into whichever folder happened to come back first. When the client
    does not name one (older client builds), the caller's own folder is used,
    with the organization-wide one as fallback.
    """
    if len(entries) > MAX_MANIFEST_ENTRIES:
        raise ApiError(
            400,
            "MANIFEST_TOO_LARGE",
            "The folder holds more files than this version can sync at once.",
        )
    if source_id is not None:
        source = await session.get(KnowledgeSource, source_id)
        if source is None or source.organization_id != organization.id:
            raise ApiError(
                404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered."
            )
        # A caller may only sync their own folder, or an org-wide one.
        if source.user_id is not None and source.user_id != user_id:
            raise ApiError(
                404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered."
            )
    else:
        from backend.knowledge.assets import _active_source

        source = await _active_source(session, organization.id, user_id)
    if source is None:
        raise ApiError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered.")
    if source.status == "disabled":
        raise ApiError(409, "SOURCE_DISABLED", "The knowledge source is disabled.")

    now = _utc_now()
    # PO rule: max 25MB per file. Checked against the manifest size so an
    # oversized file is refused BEFORE the client spends time uploading it.
    max_bytes = get_settings().upload_max_file_mb * 1024 * 1024
    found: dict[str, tuple[str, int]] = {}
    rejected: list[dict] = []
    skipped = 0
    for entry in entries:
        rel = normalize_rel_path(str(entry.get("rel_path") or ""))
        if rel is None or not _is_scannable(rel):
            skipped += 1
            continue
        digest = str(entry.get("fingerprint") or "").strip().lower()[:64]
        if not digest:
            skipped += 1
            continue
        raw_size = entry.get("size_bytes")
        size = int(raw_size) if isinstance(raw_size, int) and raw_size >= 0 else 0
        if size > max_bytes:
            rejected.append(
                {
                    "rel_path": rel,
                    "code": "UPLOAD_TOO_LARGE",
                    "limit_mb": get_settings().upload_max_file_mb,
                }
            )
            continue
        found[rel] = (digest, size)

    existing_rows = (
        (
            await session.execute(
                select(KnowledgeAsset).where(
                    KnowledgeAsset.source_id == source.id,
                    KnowledgeAsset.deleted_at.is_(None),
                    KnowledgeAsset.rel_path.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_rel_path = {row.rel_path: row for row in existing_rows}

    added = updated = deleted = 0
    new_assets: list[KnowledgeAsset] = []
    changed_assets: list[KnowledgeAsset] = []
    for rel_path, (fingerprint, size) in found.items():
        asset = by_rel_path.pop(rel_path, None)
        if asset is None:
            asset = KnowledgeAsset(
                organization_id=organization.id,
                source_id=source.id,
                name=rel_path.rsplit("/", 1)[-1],
                storage_path="",  # the client uploads the bytes on demand
                size_bytes=size,
                extension=_manifest_extension(rel_path),
                status="queued",
                # A file found in a user's folder belongs to that user. Without
                # this every discovered file would be org-visible and readable by
                # every colleague, which is exactly the leak this closes.
                owner_id=source.user_id,
                rel_path=rel_path,
                file_fingerprint=fingerprint,
                discovered_at=now,
                manifest_synced_at=now,
            )
            session.add(asset)
            new_assets.append(asset)
            added += 1
            await record_audit(
                session,
                "knowledge-asset.discovered",
                organization_id=organization.id,
                entity_type="knowledge_asset",
                entity_id=asset.id,
                detail={"rel_path": rel_path, "origin": "client_folder"},
            )
        elif asset.file_fingerprint != fingerprint:
            asset.file_fingerprint = fingerprint
            asset.size_bytes = size
            asset.status = "queued"  # US-202 FR-006: changed files re-enter the queue
            asset.version += 1  # US-203 scenario 2: new version -> reprocess job
            asset.manifest_synced_at = now
            changed_assets.append(asset)
            updated += 1
            await record_audit(
                session,
                "knowledge-asset.updated",
                organization_id=organization.id,
                entity_type="knowledge_asset",
                entity_id=asset.id,
                detail={"rel_path": rel_path, "origin": "client_folder"},
            )
        else:
            asset.manifest_synced_at = now

    for gone in by_rel_path.values():
        # US-202 FR-007 parity: the file left the owner's folder, so the asset
        # is soft-deleted and its history kept.
        gone.deleted_at = now
        deleted += 1
        await record_audit(
            session,
            "knowledge-asset.deleted",
            organization_id=organization.id,
            entity_type="knowledge_asset",
            entity_id=gone.id,
            detail={"rel_path": gone.rel_path, "origin": "client_folder"},
        )

    for created_asset in new_assets:
        await enqueue_job(session, organization.id, created_asset, "create")
    for changed in changed_assets:
        await enqueue_job(session, organization.id, changed, "reprocess")

    source.discovered_files = len(found)
    source.last_scanned_at = now
    await record_audit(
        session,
        "knowledge-source.scan.completed",
        organization_id=organization.id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={
            "scan_type": "client",
            "added": added,
            "updated": updated,
            "deleted": deleted,
        },
    )
    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "discovered_files": len(found),
        "skipped": skipped,
        # Files the client must not bother uploading (size cap) - the client
        # shows these to the owner in Persian instead of failing silently.
        "rejected": rejected,
        # The client needs these ids to upload the bytes of new/changed files.
        "pending": [
            {"asset_id": str(asset.id), "rel_path": asset.rel_path}
            for asset in (new_assets + changed_assets)
        ],
    }


async def upload_client_file(
    session: AsyncSession, organization: Organization, asset_id, upload, user_id=None
) -> dict:
    """US-201 FR-009 parity: store the bytes the client sent for one manifest entry.

    US-1606: the declared size is checked BEFORE the body is buffered, so an
    oversized file is refused instead of being read into memory first.
    """

    from backend.knowledge.assets import _validate_file

    asset = await session.get(KnowledgeAsset, asset_id)
    if asset is None or asset.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "This document was not found.")
    # The client posts bytes for an asset id it learned from the manifest. The id
    # is guessable, so without this check a member of the organization could
    # overwrite a colleague's file content by posting to their asset id.
    if asset.owner_id is not None and asset.owner_id != user_id:
        raise ApiError(404, "KNOWLEDGE_ASSET_NOT_FOUND", "This document was not found.")
    name = asset.name or "file"

    # Max 25MB per file (PO rule): refuse on the declared size first.
    declared = getattr(upload, "size", None)
    if isinstance(declared, int) and declared > get_settings().upload_max_file_mb * 1024 * 1024:
        raise ApiError(
            400,
            "UPLOAD_TOO_LARGE",
            f"File exceeds the {get_settings().upload_max_file_mb}MB limit.",
        )

    content = await upload.read()
    if not content:
        raise ApiError(400, "UPLOAD_EMPTY", "The file is empty.")
    extension = _validate_file(name, len(content))

    # One subfolder per source (PO request 2026-09: several folders per user).
    # Without it, two folders holding a same-named file would write to one path.
    from backend.knowledge.assets import _storage_dir

    target_dir = _storage_dir(
        organization.id, asset.owner_id, source_id=asset.source_id
    )
    target = target_dir / f"{asset.id}.{extension}"
    target.write_bytes(content)

    asset.storage_path = str(target)
    asset.size_bytes = len(content)
    asset.extension = extension
    asset.status = "queued"
    await record_audit(
        session,
        "knowledge-asset.synced",
        organization_id=organization.id,
        entity_type="knowledge_asset",
        entity_id=asset.id,
        detail={"rel_path": asset.rel_path, "size_bytes": len(content)},
    )
    return {"asset_id": str(asset.id), "size_bytes": len(content), "status": asset.status}
