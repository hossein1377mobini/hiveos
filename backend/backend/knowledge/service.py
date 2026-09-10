"""Ingestion folder registration + minimal scan (US-007/US-201, T-S1-8).

v0.1 scope: one local-folder knowledge source per organization, validated
before registration (readable, inside the allowed roots). The discovery of
assets and the processing pipeline belong to US-202/203 (S2); the scan here
summarizes the file count into the registration row.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.db import audit_session_factory
from backend.models import KnowledgeSource, Organization, OrganizationBrain

# US-007 security: arbitrary system paths must not be readable through the API.
_SENSITIVE_PREFIXES = (
    "c:\windows",
    "c:\program files",
    "c:\program files (x86)",
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _path_allowed(path: Path) -> bool:
    """US-007 path rules: absolute + inside configured roots (when set) and
    never under a sensitive system prefix."""
    raw = str(path).lower().rstrip("\/") + os.sep
    if any(raw.startswith(prefix + os.sep) or raw.rstrip(os.sep) == prefix for prefix in _SENSITIVE_PREFIXES):
        return False
    configured = get_settings().ingestion_allowed_roots
    if configured:
        for root in configured.split(","):
            root = root.strip()
            if not root:
                continue
            try:
                path.relative_to(Path(root))
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
        next(iter(os.scandir(path)), None)
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


async def _active_brain(session: AsyncSession, organization_id) -> OrganizationBrain | None:
    return (
        await session.execute(
            select(OrganizationBrain).where(OrganizationBrain.organization_id == organization_id)
        )
    ).scalar_one_or_none()


async def register_folder_source(session: AsyncSession, organization: Organization, path_text: str) -> dict:
    """US-007 scenario 1: validate, register (US-201), initial scan summary."""
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
    return _payload(source, "pending_files")


async def scan_source(session: AsyncSession, organization: Organization, source_id) -> dict:
    """US-007 FR-006 / scenario 4 (minimal): manual scan summary for S2."""
    source = await session.get(KnowledgeSource, source_id)
    if source is None or source.organization_id != organization.id:
        raise ApiError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "No knowledge source registered.")
    try:
        source.discovered_files = count_files(Path(source.path))
        source.last_scanned_at = _utc_now()
    except OSError as exc:
        async with audit_session_factory() as audit_session:
            await record_audit(
                audit_session,
                "knowledge-source.scan.failed",
                organization_id=organization.id,
                entity_type="knowledge_source",
                entity_id=source.id,
                detail={"reason": str(exc)},
            )
            await audit_session.commit()
        raise ApiError(400, "INGESTION_PATH_NOT_READABLE", "The server cannot read this folder.") from exc

    await record_audit(
        session,
        "knowledge-source.scan.started",
        organization_id=organization.id,
        entity_type="knowledge_source",
        entity_id=source.id,
    )
    await record_audit(
        session,
        "knowledge-source.scan.completed",
        organization_id=organization.id,
        entity_type="knowledge_source",
        entity_id=source.id,
        detail={"discovered_files": source.discovered_files},
    )
    return _payload(source, source.discovered_files)


def _payload(source: KnowledgeSource, files_state) -> dict:
    return {
        "id": source.id,
        "path": source.path,
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
