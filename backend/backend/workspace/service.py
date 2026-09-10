"""Workspace initialization service (US-004, T-S1-6).

The primary workspace row already exists from organization registration
(US-001 FR-002). Initialization prepares the settings with the fixed system
defaults and the local storage location, then marks the workspace ready.

Scenario 2: if storage preparation fails, the failed state is persisted in
its own committed transaction so the user can retry (the request transaction
itself rolls back).
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.db import audit_session_factory
from backend.models import Organization, Workspace, WorkspaceSettings


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _primary_workspace(session: AsyncSession, organization_id) -> Workspace | None:
    return (
        await session.execute(
            select(Workspace).where(
                Workspace.organization_id == organization_id,
                Workspace.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _mark_failed(workspace_id, organization_id, reason: str) -> None:
    """US-004 scenario 2: persist 'failed' + the failure event for retry."""
    async with audit_session_factory() as audit_session:
        workspace = await audit_session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is not None:
            workspace.status = "failed"
        await record_audit(
            audit_session,
            "workspace.initialization.failed",
            organization_id=organization_id,
            entity_type="workspace",
            entity_id=workspace_id,
            detail={"reason": reason},
        )
        await audit_session.commit()


def _payload(workspace: Workspace) -> dict:
    return {
        "workspace_id": workspace.id,
        "status": "ready",
        "settings": {
            # US-004 FR-003: fixed system defaults, never user input.
            "language": "fa-IR",
            "timezone": "Asia/Tehran",
            "default_locale": "fa-IR",
            "date_format": "yyyy/MM/dd",
            "number_format": "fa-IR",
        },
    }


async def initialize_workspace(session: AsyncSession, organization: Organization) -> dict:
    settings = get_settings()

    workspace = await _primary_workspace(session, organization.id)
    if workspace is None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "No workspace exists for this organization.")

    existing = await session.get(WorkspaceSettings, workspace.id)
    if existing is not None and workspace.initialized_at is not None:
        # Idempotent: a retry after an unclear state returns the ready workspace.
        return _payload(workspace)

    await record_audit(
        session,
        "workspace.initialization.started",
        organization_id=organization.id,
        entity_type="workspace",
        entity_id=workspace.id,
    )

    # US-004 FR-004: prepare the storage location (local disk in v0.1).
    storage_root = str(Path(settings.storage_root) / str(organization.tenant_id) / str(workspace.id))
    try:
        Path(storage_root).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        await _mark_failed(workspace.id, organization.id, str(exc))
        raise ApiError(
            500,
            "WORKSPACE_INITIALIZATION_FAILED",
            "Workspace initialization failed. Please retry.",
        ) from exc

    session.add(WorkspaceSettings(workspace_id=workspace.id))
    workspace.storage_root = storage_root
    workspace.initialized_at = _utc_now()
    workspace.status = "active"

    await record_audit(
        session,
        "workspace.ready",
        organization_id=organization.id,
        entity_type="workspace",
        entity_id=workspace.id,
        detail={"storage_root": storage_root},
    )
    return _payload(workspace)
