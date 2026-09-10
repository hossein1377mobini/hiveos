"""Brain initialization service (US-005, T-S1-7).

Creates the base Organization Brain, the empty knowledge repository and the
vector-index marker in one transactional step. The system prompt is rendered
from the US-1609 template with the organization's business description
injected (US-005 FR-005, Amendment 2 - US-001 owns collecting it).

Scenario 2: on failure, the failed state and the failure event are persisted
in their own committed transaction; the request transaction rolls back, so
no partial structure survives (retry is possible).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.brain.prompt_template import DEFAULT_SYSTEM_PROMPT_TEMPLATE
from backend.db import audit_session_factory
from backend.models import (
    KnowledgeRepository,
    Organization,
    OrganizationBrain,
    VectorIndex,
    Workspace,
)

_FALLBACK_DESCRIPTION = "توصیف کسب‌وکار برای این سازمان ثبت نشده است."


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _render_system_prompt(organization: Organization) -> str:
    return DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(
        business_description=organization.business_description or _FALLBACK_DESCRIPTION
    )


async def _primary_workspace(session: AsyncSession, organization_id) -> Workspace | None:
    return (
        await session.execute(
            select(Workspace).where(
                Workspace.organization_id == organization_id,
                Workspace.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _mark_failed(organization_id, reason: str) -> None:
    """US-005 scenario 2: persist the failure event for audit + retry."""
    async with audit_session_factory() as audit_session:
        await record_audit(
            audit_session,
            "brain.initialization.failed",
            organization_id=organization_id,
            entity_type="organization_brain",
            entity_id=organization_id,
            detail={"reason": reason},
        )
        await audit_session.commit()


def _payload(organization_id, workspace_id) -> dict:
    return {
        "brain_status": "ready",
        "knowledge_repository_status": "ready",
        "vector_index_status": "created",
        "default_language": "fa-IR",
        "workspace_id": workspace_id,
        "organization_id": organization_id,
    }


async def initialize_brain(session: AsyncSession, organization: Organization) -> dict:
    existing = await session.execute(
        select(OrganizationBrain).where(OrganizationBrain.organization_id == organization.id)
    )
    brain = existing.scalar_one_or_none()
    if brain is not None and brain.status == "ready":
        # Idempotent: a repeat call returns the ready Brain (retry-safe).
        return _payload(organization.id, brain.workspace_id)

    await record_audit(
        session,
        "brain.initialization.started",
        organization_id=organization.id,
        entity_type="organization_brain",
        entity_id=organization.id,
    )

    workspace = await _primary_workspace(session, organization.id)
    if workspace is None or workspace.initialized_at is None:
        raise ApiError(
            409,
            "BRAIN_WORKSPACE_NOT_READY",
            "The workspace must be initialized before the organization brain.",
        )

    try:
        brain = OrganizationBrain(
            organization_id=organization.id,
            workspace_id=workspace.id,
            status="ready",
            system_prompt=_render_system_prompt(organization),
        )
        session.add(brain)
        await session.flush()

        repository = KnowledgeRepository(
            organization_id=organization.id,
            workspace_id=workspace.id,
            brain_id=brain.id,
            status="ready",
        )
        session.add(repository)
        await session.flush()
        await record_audit(
            session,
            "knowledge.repository.created",
            organization_id=organization.id,
            entity_type="knowledge_repository",
            entity_id=repository.id,
        )

        index = VectorIndex(organization_id=organization.id, brain_id=brain.id, status="created")
        session.add(index)
        await session.flush()
        await record_audit(
            session,
            "vector.index.created",
            organization_id=organization.id,
            entity_type="vector_index",
            entity_id=index.id,
        )
        await record_audit(
            session,
            "brain.created",
            organization_id=organization.id,
            entity_type="organization_brain",
            entity_id=brain.id,
        )
        await record_audit(
            session,
            "brain.ready",
            organization_id=organization.id,
            entity_type="organization_brain",
            entity_id=brain.id,
        )
    except Exception as exc:
        await _mark_failed(organization.id, str(exc))
        raise ApiError(
            500,
            "BRAIN_INITIALIZATION_FAILED",
            "Brain initialization failed. Please retry.",
        ) from exc

    return _payload(organization.id, workspace.id)
