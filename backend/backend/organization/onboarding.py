"""Onboarding status + pending expiry (US-007 resume / C2-C3, T-S1-8).

C2: the UI resumes onboarding from the first incomplete step - this endpoint
reports exactly what is done (organization active, workspace, brain, source).
C3: a pending organization whose window elapsed flips to EXPIRED with an
audit event before anything else is reported.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import record_audit
from backend.enums_helpers import status_value
from backend.models import KnowledgeSource, Organization, OrganizationBrain, OrganizationStatus, Workspace


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _expire_pending_organization(
    session: AsyncSession, organization: Organization
) -> bool:
    """C3: a pending org past its expiry window becomes EXPIRED (persisted)."""
    now = _utc_now()
    expiry = organization.pending_expires_at
    if expiry is None:
        return False
    expiry = expiry if not hasattr(expiry, "to_datetime") else expiry.to_datetime()
    if organization.status != OrganizationStatus.PENDING_OWNER_REGISTRATION.value:
        return False
    if expiry > now:
        return False
    organization.status = OrganizationStatus.EXPIRED
    await record_audit(
        session,
        "organization.expired",
        organization_id=organization.id,
        entity_type="organization",
        entity_id=organization.id,
        detail={"pending_expires_at": expiry.isoformat()},
    )
    return True


async def onboarding_status(session: AsyncSession, organization: Organization) -> dict:
    expired = await _expire_pending_organization(session, organization)

    workspace = (
        await session.execute(
            select(Workspace).where(
                Workspace.organization_id == organization.id,
                Workspace.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()
    brain = (
        await session.execute(
            select(OrganizationBrain).where(OrganizationBrain.organization_id == organization.id)
        )
    ).scalar_one_or_none()
    source = (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.organization_id == organization.id)
        )
    ).scalar_one_or_none()

    # US-1207 (minimal subscription): plan + expiry ride on every status read.
    plan_expires_at = organization.plan_expires_at
    plan_expired = (
        plan_expires_at is not None and plan_expires_at.astimezone(UTC) < datetime.now(UTC)
    )
    return {
        "organization_status": status_value(organization.status),
        "expired": expired,
        "workspace_ready": bool(workspace is not None and workspace.initialized_at is not None),
        "brain_ready": bool(brain is not None and brain.status == "ready"),
        "knowledge_source": None
        if source is None
        else {"id": source.id, "path": source.path, "status": source.status},
        "subscription": {
            "plan": organization.plan,
            "expires_at": plan_expires_at,
            "expired": plan_expired,
        },
        # C2: the first incomplete step drives the UI redirect.
        "next_step": _next_step(organization, workspace, brain, source),
    }


def _next_step(organization: Organization, workspace, brain, source) -> str:
    if organization.status == OrganizationStatus.PENDING_OWNER_REGISTRATION.value:
        return "owner"
    if organization.status == OrganizationStatus.EXPIRED.value:
        return "expired"
    if workspace is None or workspace.initialized_at is None:
        return "workspace"
    if brain is None or brain.status != "ready":
        return "brain"
    if source is None:
        return "knowledge_source"
    return "chat"
