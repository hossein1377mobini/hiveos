"""Ingestion folder: registration + full scanner (US-007/US-201/US-202).

v0.1 scope: one local-folder knowledge source per organization, validated
before registration (readable, inside the allowed roots). The scanner
(US-202) walks the folder recursively, fingerprints every file
(path|size|mtime), and reconciles KnowledgeAsset rows: added files enter
the queue ('queued'), changed files re-enter it, and missing files are
soft-deleted with their history kept (FR-007). Every run lands in
scan_history (Amendment 2 / C11) - the 'running' row is also the
single-concurrent-scan guard.
"""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.db import audit_session_factory
from backend.knowledge.assets import ALLOWED_EXTENSIONS
from backend.knowledge.processing import enqueue_job
from backend.models import (
    KnowledgeAsset,
    KnowledgeSource,
    Organization,
    OrganizationBrain,
    ScanHistory,
)

# US-007 security: arbitrary system paths must not be readable through the API.
_SENSITIVE_PREFIXES = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/root",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/var",
)

_SCAN_FILE_LIMIT = 10_000
SCAN_TYPES = ("initial", "scheduled", "manual")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _path_allowed(path: Path) -> bool:
    """US-007 path rules: absolute + inside configured roots (when set) and
    never under a sensitive system prefix.

    B4 (external review): the check runs on the RESOLVED path (symlinks and
    `..` segments eliminated), not the raw string - otherwise
    `C:/allowed/../Windows` passes the string check and os.walk resolves it.
    """
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    raw = str(resolved).lower().rstrip("\\/") + os.sep
    if any(raw.startswith(prefix + os.sep) or raw.rstrip(os.sep) == prefix for prefix in _SENSITIVE_PREFIXES):
        return False
    configured = get_settings().ingestion_allowed_roots
    if configured:
        for root in configured.split(","):
            root = root.strip()
            if not root:
                continue
            try:
                resolved.relative_to(Path(root).resolve(strict=False))
                return True
            except ValueError:
                continue
        return False
    return True


def validate_folder(path_text: str) -> Path:
    """US-007 FR-002 / validation rules: exists, readable, allowed."""
    if not path_text or not path_text.strip():
        raise ApiError(400, "INGESTION_PATH_REQUIRED", "Please enter a folder path.")
    path = Path(path_text.strip().strip('"'))
    if not path.is_absolute():
        raise ApiError(400, "INGESTION_PATH_NOT_ABSOLUTE", "The folder path must be absolute.")
    if not _path_allowed(path):
        raise ApiError(
            400, "INGESTION_PATH_NOT_ALLOWED", "This path is outside the allowed scope of the system."
        )
    if not path.is_dir():
        raise ApiError(400, "INGESTION_PATH_NOT_FOUND", "The folder does not exist.")
    try:
        with os.scandir(path) as entries:
            next(iter(entries), None)
    except OSError as exc:
        raise ApiError(
            400, "INGESTION_PATH_NOT_READABLE", "The server cannot read this folder."
        ) from exc
    return path


def count_files(path: Path) -> int:
    total = 0
    for _root, _dirs, files in os.walk(path):
        total += len(files)
        if total > _SCAN_FILE_LIMIT:
            return _SCAN_FILE_LIMIT
    return total


def _walk_fingerprints(root: Path) -> dict[str, tuple[str, int]]:
    """US-202 FR-004: recursive walk -> {rel_path: (fingerprint, size)}.

    Fingerprint = sha256(rel_path|size|mtime_ns) - change detection without
    reading file contents (FR-005). Content-level change detection beyond
    mtime is the classification concern (US-205, T-S2-4).
    """
    found: dict[str, tuple[str, int]] = {}
    resolved_root = root.resolve(strict=False)
    limit_hit = False
    for current_root, _dirs, files in os.walk(root):
        # B4 (external review): skip anything that resolves outside the root
        # (junction/symlink escape mid-walk).
        for name in files:
            full = Path(current_root) / name
            try:
                if not full.resolve(strict=False).is_relative_to(resolved_root):
                    continue
            except OSError:
                continue
            rel = full.relative_to(root).as_posix()
            # PO decision 2026-09-12: the folder scan applies the SAME US-205
            # format table as the upload path - an off-list file is skipped
            # instead of entering the pipeline (and the review queue).
            if full.suffix.lstrip(".").lower() not in ALLOWED_EXTENSIONS:
                continue
            try:
                stat = full.stat()
            except OSError:
                continue  # vanishing mid-walk - next scan catches it
            digest = hashlib.sha256(
                f"{rel}|{stat.st_size}|{stat.st_mtime_ns}".encode()
            ).hexdigest()
            found[rel] = (digest, stat.st_size)
            if len(found) >= _SCAN_FILE_LIMIT:
                # E: this used to 'return found' from inside the os.walk loop,
                # which closed the generator early and leaked its directory
                # handle. Break out and let the loop finish normally.
                limit_hit = True
                break
        if limit_hit:
            break
    return found


async def _active_brain(session: AsyncSession, organization_id) -> OrganizationBrain | None:
    return (
        await session.execute(
            select(OrganizationBrain).where(OrganizationBrain.organization_id == organization_id)
        )
    ).scalar_one_or_none()


async def register_folder_source(session: AsyncSession, organization: Organization, path_text: str) -> dict:
    """US-201 scenario 1: validate, register, then the automatic first scan."""
    brain = await _active_brain(session, organization.id)
    if brain is None or brain.status != "ready":
        raise ApiError(
            409, "KNOWLEDGE_BRAIN_NOT_READY", "Complete the previous onboarding steps first."
        )

    existing = (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.organization_id == organization.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        # v0.1 keeps a single folder; re-registering validates and updates it.
        source = existing
        source.path = str(validate_folder(path_text))
    else:
        source = KnowledgeSource(
            organization_id=organization.id,
            workspace_id=brain.workspace_id,
            brain_id=brain.id,
            path=str(validate_folder(path_text)),
        )
        session.add(source)
        await session.flush()

    await record_audit(
        session,
        "knowledge-source.created",
        organization_id=organization.id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={"path": source.path, "source_type": "local_folder"},
    )
    # US-202 FR-001: the first scan runs automatically after registration.
    await run_scan(session, organization.id, source, "initial")
    return _payload(source, source.discovered_files)


async def scan_source(session: AsyncSession, organization: Organization, source_id) -> dict:
    """US-202 FR-003 / scenario 4: the manual Scan Now entry point."""
    source = await session.get(KnowledgeSource, source_id)
    if source is None or source.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered.")
    result = await run_scan(session, organization.id, source, "manual")
    return {**_payload(source, source.discovered_files), **result}


async def run_scan(
    session: AsyncSession, organization_id, source: KnowledgeSource, scan_type: str
) -> dict:
    """US-202 core: one full scan run of any type (FR-001..FR-009).

    Walks the folder, reconciles assets, and records the history row. The
    request transaction commits the assets; a failed scan additionally
    persists its history + audit through the independent audit session.
    """
    if source.status == "disabled":
        raise ApiError(409, "SOURCE_DISABLED", "Enable the knowledge source before scanning.")

    running = (
        await session.execute(
            select(ScanHistory.id).where(
                ScanHistory.source_id == source.id, ScanHistory.status == "running"
            )
        )
    ).scalar_one_or_none()
    if running is not None:
        raise ApiError(
            409, "SCAN_ALREADY_RUNNING", "A scan is already running for this source."
        )

    # US-202 scenario 3: a failed scan must persist its history + audit even
    # though the request transaction rolls back - so the walk happens BEFORE
    # any request-txn write, and failure writes go through the audit session.
    try:
        root = Path(source.path)
        if not root.is_dir():
            raise OSError(f"scan root vanished: {source.path}")
        found = _walk_fingerprints(root)
    except OSError as exc:
        async with audit_session_factory() as audit_session:
            audit_session.add(
                ScanHistory(
                    source_id=source.id,
                    scan_type=scan_type,
                    status="failed",
                    error_detail=str(exc),
                    finished_at=_utc_now(),
                )
            )
            await record_audit(
                audit_session,
                "knowledge-source.scan.failed",
                organization_id=organization_id,
                entity_type="knowledge_source",
                entity_id=source.id,
                detail={"reason": str(exc), "scan_type": scan_type},
            )
            await audit_session.commit()
        raise ApiError(400, "INGESTION_PATH_NOT_READABLE", "The server cannot read this folder.") from exc

    history = ScanHistory(source_id=source.id, scan_type=scan_type, status="running")
    session.add(history)
    await session.flush()

    await record_audit(
        session,
        "knowledge-source.scan.started",
        organization_id=organization_id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={"scan_type": scan_type, "history_id": str(history.id)},
    )

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
    now = _utc_now()
    new_assets: list[KnowledgeAsset] = []
    changed_assets: list[KnowledgeAsset] = []
    for rel_path, (fingerprint, size) in found.items():
        asset = by_rel_path.pop(rel_path, None)
        if asset is None:
            asset = KnowledgeAsset(
                organization_id=organization_id,
                source_id=source.id,
                name=rel_path.rsplit("/", 1)[-1],
                storage_path="",  # folder files stay in place
                size_bytes=size,
                extension=rel_path.rsplit(".", 1)[-1].lower()[:10] if "." in rel_path else "",
                status="queued",
                rel_path=rel_path,
                file_fingerprint=fingerprint,
                discovered_at=now,
            )
            session.add(asset)
            new_assets.append(asset)
            added += 1
            await record_audit(
                session,
                "knowledge-asset.discovered",
                organization_id=organization_id,
                entity_type="knowledge_asset",
                entity_id=asset.id,
                detail={"rel_path": rel_path},
            )
        elif asset.file_fingerprint != fingerprint:
            asset.file_fingerprint = fingerprint
            asset.size_bytes = size
            asset.status = "queued"  # US-202 FR-006: changed files re-enter the queue
            asset.version += 1  # US-203 scenario 2: new version -> reprocess job
            changed_assets.append(asset)
            updated += 1
            await record_audit(
                session,
                "knowledge-asset.updated",
                organization_id=organization_id,
                entity_type="knowledge_asset",
                entity_id=asset.id,
                detail={"rel_path": rel_path},
            )

    for gone in by_rel_path.values():
        # US-202 FR-007: mark deleted, keep the row (history preserved).
        gone.deleted_at = now
        deleted += 1
        await record_audit(
            session,
            "knowledge-asset.deleted",
            organization_id=organization_id,
            entity_type="knowledge_asset",
            entity_id=gone.id,
            detail={"rel_path": gone.rel_path},
        )

    # US-203: one processing job per new/changed asset (FR-003 dedups);
    # scheduled background runs queue at low priority (priority rules).
    priority = "low" if scan_type == "scheduled" else "normal"
    for created_asset in new_assets:
        await enqueue_job(session, organization_id, created_asset, "create", priority)
    for changed in changed_assets:
        await enqueue_job(session, organization_id, changed, "reprocess", priority)

    history.status = "success"
    history.files_added = added
    history.files_updated = updated
    history.files_deleted = deleted
    history.discovered_files = len(found)
    history.finished_at = _utc_now()

    source.discovered_files = len(found)
    source.last_scanned_at = history.finished_at

    await record_audit(
        session,
        "knowledge-source.scan.completed",
        organization_id=organization_id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={
            "scan_type": scan_type,
            "added": added,
            "updated": updated,
            "deleted": deleted,
        },
    )
    return {
        "scan_id": history.id,
        "scan_type": scan_type,
        "files_added": added,
        "files_updated": updated,
        "files_deleted": deleted,
        "discovered_files": len(found),
    }


async def scan_history(session: AsyncSession, organization: Organization, source_id) -> list[dict]:
    """US-202 FR-009 (Amendment 2, C11): the last N scans of one source."""
    source = await session.get(KnowledgeSource, source_id)
    if source is None or source.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered.")
    limit = 10
    rows = (
        (
            await session.execute(
                select(ScanHistory)
                .where(ScanHistory.source_id == source.id)
                .order_by(ScanHistory.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "scan_type": row.scan_type,
            "status": row.status,
            "files_added": row.files_added,
            "files_updated": row.files_updated,
            "files_deleted": row.files_deleted,
            "discovered_files": row.discovered_files,
            "error_detail": row.error_detail,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }
        for row in rows
    ]


async def find_due_sources(session: AsyncSession, now: datetime) -> list[KnowledgeSource]:
    """US-202 FR-002: active sources whose scan interval has elapsed."""
    rows = (
        (await session.execute(select(KnowledgeSource).where(KnowledgeSource.status == "active")))
        .scalars()
        .all()
    )
    due: list[KnowledgeSource] = []
    for source in rows:
        if source.last_scanned_at is None:
            continue  # initial scan happens at registration
        # E: stamping tzinfo unconditionally shifts an already-aware value by
        # the server offset, which silently stops scheduled scans forever.
        last = source.last_scanned_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed = (now - last).total_seconds() / 60.0
        if elapsed >= source.scan_interval_minutes:
            due.append(source)
    return due


def _payload(source: KnowledgeSource, files_state) -> dict:
    label = source.path_label or source.path
    return {
        "id": source.id,
        "path": label,
        "path_label": label,
        "source_type": source.source_type,
        "status": source.status,
        "file_state": files_state,  # 'pending_files' (scenario 3) or the discovered count
        "scan_interval_minutes": source.scan_interval_minutes,
        "last_scanned_at": source.last_scanned_at,
    }


async def get_source(session: AsyncSession, organization: Organization) -> dict | None:
    source = (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.organization_id == organization.id)
        )
    ).scalar_one_or_none()
    if source is None:
        return None
    return _payload(source, source.discovered_files)
