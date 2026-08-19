"""US-005 baseline Organization Brain initialization (transactional).

Creates, in ONE transaction, the v0.1 RAG substrate for an Organization: an
empty Knowledge Repository, a pgvector-backed Vector Index (dim=1024), and the
basic retrieval config. ``embedding_provider`` is read from the Organization's
US-001 AI model config (``Organization.ai_provider``) — never chosen
independently (FR-005) — and ``default_language`` inherits from the Workspace
settings (US-004), falling back to the org's own language.

Idempotency: a ready Brain for the org short-circuits to its current values.
Failure-safety: any unexpected exception rolls the transaction back (no partial
structures survive — FR "هیچ ساختار ناقصی باقی نماند"), writes a
``brain.initialization.failed`` audit entry in a separate commit, and raises
``InternalError`` so a later call may retry.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, InternalError
from app.models import (
    AuditLog,
    KnowledgeRepository,
    Organization,
    OrganizationBrain,
    VectorIndex,
    Workspace,
)
from app.schemas import BrainInitialized, BrainRagConfig

# Basic RAG retrieval config for v0.1 (top-K chunks, chunk sizing, overlap).
_DEFAULT_RETRIEVAL_CONFIG: dict = {"topK": 5, "chunkSize": 512, "overlap": 64}


def _brain_response(
    brain: OrganizationBrain, repo: KnowledgeRepository, index: VectorIndex
) -> BrainInitialized:
    """Shape the persisted Brain triple into the contract-exact response."""
    return BrainInitialized(
        brainId=brain.id,
        knowledgeRepositoryId=repo.id,
        vectorIndexId=index.id,
        status=brain.status,
        rag=BrainRagConfig(
            embeddingProvider=brain.embedding_provider,
            defaultLanguage=brain.default_language,
        ),
    )


def _audit_payload(*, extras: dict | None = None) -> dict:
    """Non-secret audit payload — the provider NAME only, never the apiKey."""
    return (extras or {}).copy()


async def _load_existing_ready_brain(
    session: AsyncSession, org: Organization
) -> tuple[OrganizationBrain, KnowledgeRepository, VectorIndex] | None:
    """Return the org's ready Brain + children if present (idempotency), else None."""
    brain = (
        await session.execute(
            select(OrganizationBrain).where(
                OrganizationBrain.organization_id == org.id,
                OrganizationBrain.status == "ready",
            )
        )
    ).scalar_one_or_none()
    if brain is None:
        return None

    repo = (
        await session.execute(
            select(KnowledgeRepository).where(KnowledgeRepository.brain_id == brain.id)
        )
    ).scalar_one_or_none()
    index = (
        await session.execute(
            select(VectorIndex).where(VectorIndex.brain_id == brain.id)
        )
    ).scalar_one_or_none()

    # A ready brain is always created atomically with its repo + index; if any
    # child is missing the row is corrupt — fall through to a fresh attempt.
    if repo is None or index is None:
        return None
    return brain, repo, index


async def initialize_brain(session: AsyncSession, org: Organization) -> BrainInitialized:
    """Initialize the baseline Organization Brain for an active Organization.

    Raises ``ConflictError`` when the org is not active or its Workspace is not
    ready (US-004 prerequisite), and ``InternalError`` on unexpected failure.
    """
    if org.status != "active":
        raise ConflictError("organization is not active")

    workspace = (
        await session.execute(
            select(Workspace).where(
                Workspace.organization_id == org.id,
                Workspace.status == "ready",
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise ConflictError("workspace is not ready")

    # Idempotent reuse: a prior successful run returns its existing values.
    existing = await _load_existing_ready_brain(session, org)
    if existing is not None:
        return _brain_response(*existing)

    # default_language: inherit from Workspace settings (US-004), else org fallback.
    settings = workspace.settings or {}
    default_language = settings.get("language") or org.language

    try:
        brain = OrganizationBrain(
            tenant_id=org.tenant_id,
            organization_id=org.id,
            workspace_id=workspace.id,
            status="ready",
            embedding_provider=org.ai_provider,
            default_language=default_language,
            retrieval_config=_DEFAULT_RETRIEVAL_CONFIG,
        )
        session.add(brain)
        await session.flush()

        repo = KnowledgeRepository(
            brain_id=brain.id,
            tenant_id=org.tenant_id,
            organization_id=org.id,
            status="empty",
        )
        session.add(repo)
        await session.flush()

        index = VectorIndex(
            brain_id=brain.id,
            knowledge_repository_id=repo.id,
            tenant_id=org.tenant_id,
            organization_id=org.id,
            provider=org.ai_provider,
            dimensions=1024,
            status="ready",
        )
        session.add(index)
        await session.flush()

        session.add_all(
            [
                AuditLog(
                    tenant_id=org.tenant_id,
                    action="brain.ready",
                    payload=_audit_payload(
                        extras={
                            "organization_id": str(org.id),
                            "brain_id": str(brain.id),
                            "embedding_provider": brain.embedding_provider,
                        }
                    ),
                ),
                AuditLog(
                    tenant_id=org.tenant_id,
                    action="knowledge.repository.created",
                    payload=_audit_payload(
                        extras={
                            "organization_id": str(org.id),
                            "brain_id": str(brain.id),
                            "knowledge_repository_id": str(repo.id),
                        }
                    ),
                ),
                AuditLog(
                    tenant_id=org.tenant_id,
                    action="vector.index.created",
                    payload=_audit_payload(
                        extras={
                            "organization_id": str(org.id),
                            "brain_id": str(brain.id),
                            "vector_index_id": str(index.id),
                            "dimensions": index.dimensions,
                        }
                    ),
                ),
            ]
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — roll back, audit failure in a fresh tx, surface.
        await session.rollback()
        try:
            async with session.begin():
                session.add(
                    AuditLog(
                        tenant_id=org.tenant_id,
                        action="brain.initialization.failed",
                        payload=_audit_payload(
                            extras={"organization_id": str(org.id)}
                        ),
                    )
                )
        except Exception:  # noqa: BLE001 — audit best-effort; never mask the original failure.
            pass
        raise InternalError("brain initialization failed") from exc


    return _brain_response(brain, repo, index)
