"""US-004: initialize the organization's single Workspace (transactional).

The Workspace already exists (created in US-001, one per org enforced by the
``uq_workspaces_one_per_org`` UNIQUE constraint) — this endpoint flips it from
``pending`` to ``ready`` and (re)applies the default settings inherited from
US-001. It never creates a second Workspace.

Behaviour:
- The organization must be ``active`` (OTP-verified in US-003), else 409.
- Idempotent: if the workspace is already ``ready`` it is returned as-is with
  no side effects.
- ``pending``/``failed`` → ``ready``, settings written from the org's recorded
  defaults (server-side fa-IR / Asia/Tehran per PO), audit-logged, committed.
- Any unexpected failure inside the transaction rolls back the work, persists a
  ``failed`` marker + ``workspace.initialization.failed`` audit row (so the
  state is observable and a later call may retry ``failed`` → ``ready``), then
  raises ``InternalError`` (500).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, InternalError, NotFoundError
from app.models import AuditLog, Organization, Workspace
from app.schemas import WorkspaceInitialized, WorkspaceSettings

# Fixed locale/format defaults (PO decision): server-side fa-IR / Iran /
# Asia-Teheran. language and timeZone are inherited from the Organization
# (US-001), which already carries these same defaults but may be edited later.
_DATE_FORMAT = "YYYY/MM/DD"
_NUMBER_FORMAT = "fa-IR"
_DEFAULT_LOCALE = "fa-IR"


def _build_settings(org: Organization) -> dict[str, str]:
    """Workspace settings inherited from the org's recorded US-001 defaults."""
    return {
        "language": org.language,
        "timeZone": org.time_zone,
        "dateFormat": _DATE_FORMAT,
        "numberFormat": _NUMBER_FORMAT,
        "defaultLocale": _DEFAULT_LOCALE,
    }


async def _mark_failed(
    session: AsyncSession, *, org_id, tenant_id, ws_id
) -> None:
    """Persist the failed marker + failure audit entry (commits)."""
    ws = await session.get(Workspace, ws_id)
    if ws is not None:
        ws.status = "failed"

    session.add(
        AuditLog(
            tenant_id=tenant_id,
            action="workspace.initialization.failed",
            actor_ref=None,
            payload={
                "organization_id": str(org_id),
                "workspace_id": str(ws_id),
            },
        )
    )
    await session.commit()


async def initialize_workspace(
    session: AsyncSession, org: Organization
) -> WorkspaceInitialized:
    if org.status != "active":
        raise ConflictError("organization is not active")

    result = await session.execute(
        select(Workspace).where(Workspace.organization_id == org.id)
    )
    ws = result.scalar_one_or_none()
    if ws is None:
        raise NotFoundError("workspace not found")

    # Capture identifiers up front so the failure path does not depend on
    # objects that expire after a rollback.
    org_id = org.id
    tenant_id = org.tenant_id
    ws_id = ws.id

    # Idempotent: already initialized -> return the existing result untouched.
    if ws.status == "ready":
        return WorkspaceInitialized(
            workspaceId=ws_id,
            status="ready",
            settings=WorkspaceSettings(**ws.settings),
        )

    settings = _build_settings(org)

    try:
        ws.status = "ready"
        ws.settings = settings
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                action="workspace.ready",
                actor_ref=None,
                payload={
                    "organization_id": str(org_id),
                    "workspace_id": str(ws_id),
                },
            )
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Persist the failure state + audit so it is observable and retryable
        # (failed -> ready on a later call), rather than leaving the workspace
        # silently stuck in pending.
        try:
            await _mark_failed(session, org_id=org_id, tenant_id=tenant_id, ws_id=ws_id)
        except Exception:
            await session.rollback()
        raise InternalError("workspace initialization failed") from exc

    return WorkspaceInitialized(
        workspaceId=ws_id,
        status="ready",
        settings=WorkspaceSettings(**settings),
    )
