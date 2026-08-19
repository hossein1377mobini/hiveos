"""US-008 onboarding completion logic (EPIC-01 final wave).

Determines how far an Organization has progressed through the mandatory
Bootstrap steps (US-001..US-005 + the US-007 ingestion-folder watch) and, when
they are all satisfied, marks onboarding ``completed`` exactly once — writing
the ``onboarding.completed`` audit entry.

Step semantics (each is independently checkable against the current row state):

- ``register-organization`` — inherently satisfied: ``require_org_session`` has
  already resolved a live Organization for this session, so this step is never
  reported missing.
- ``owner-account`` — an ``Owner`` row exists for the org (any status, US-002).
- ``verify-owner`` — that Owner is ``active`` (US-003 OTP; implies the org is
  active too), i.e. ``Owner.status == "active"``.
- ``workspace`` — the org's single ``Workspace`` is ``ready`` (US-004).
- ``brain`` — an ``OrganizationBrain`` exists with ``status == "ready"``
  (US-005).
- ``ingestion-folder`` — an ``IngestionFolderConfig`` row is ``active``
  (US-007, FR-001: no ready document is required — the watch is continuous).

Status derivation:

- ``completed``  — an ``OrganizationOnboarding`` row with ``completed_at``
  exists.
- ``in_progress`` — no completion row, but at least one step beyond
  ``register-organization`` is done.
- ``pending``    — no completion row and nothing beyond registration is done
  yet (a freshly registered org before its Owner is created).

The registration step's trivial "done" state does NOT by itself count as
progress, otherwise every session-resolved org would read ``in_progress`` and
``pending`` would be unreachable.

Transaction convention: callers (the API layer, via ``require_org_session``)
already hold an open transaction from the dependency reads; these functions run
inside it and ``commit()`` explicitly — never a nested ``session.begin()``.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    IngestionFolderConfig,
    Organization,
    OrganizationBrain,
    OrganizationOnboarding,
    Owner,
    Workspace,
)
from app.schemas import OnboardingCompleted, OnboardingIncomplete, OnboardingStatus

# Mandatory steps in contract (docs/openapi.yaml) order.
_STEP_ORDER: list[str] = [
    "register-organization",
    "owner-account",
    "verify-owner",
    "workspace",
    "brain",
    "ingestion-folder",
]

# Steps that actually represent progress, i.e. everything after
# ``register-organization`` (which a live session guarantees is already done).
_CHECKABLE_STEPS: list[str] = _STEP_ORDER[1:]


def _to_schema(status: str, missing: list[str]) -> OnboardingStatus:
    """Wrap the (status, missing) tuple into the contract-exact response.

    ``missingSteps`` is only meaningful when the status is ``in_progress``
    (per the OpenAPI contract); it is omitted for ``pending``/``completed``.
    """
    return OnboardingStatus(
        onboardingStatus=status,
        missingSteps=missing if status == "in_progress" else None,
    )


async def compute_onboarding_status(
    session: AsyncSession, org: Organization
) -> tuple[str, list[str]]:
    """Check each mandatory step; return ``(status_str, missing_step_ids)``.

    ``missing`` lists the incomplete step ids in contract order. As noted
    above, ``register-organization`` is never reported because the session has
    already resolved an existing Organization.
    """
    missing: list[str] = []

    # owner-account + verify-owner (US-002 / US-003)
    owner = (
        await session.execute(
            select(Owner).where(Owner.organization_id == org.id)
        )
    ).scalar_one_or_none()
    if owner is None:
        missing.append("owner-account")
        missing.append("verify-owner")
    elif owner.status != "active":
        missing.append("verify-owner")

    # workspace (US-004)
    workspace = (
        await session.execute(
            select(Workspace).where(Workspace.organization_id == org.id)
        )
    ).scalar_one_or_none()
    if workspace is None or workspace.status != "ready":
        missing.append("workspace")

    # brain (US-005)
    brain = (
        await session.execute(
            select(OrganizationBrain).where(
                OrganizationBrain.organization_id == org.id,
                OrganizationBrain.status == "ready",
            )
        )
    ).scalar_one_or_none()
    if brain is None:
        missing.append("brain")

    # ingestion-folder (US-007) — active watch, no ready document required (FR-001)
    folder = (
        await session.execute(
            select(IngestionFolderConfig).where(
                IngestionFolderConfig.organization_id == org.id,
                IngestionFolderConfig.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if folder is None:
        missing.append("ingestion-folder")

    # completion marker (US-008)
    completed = (
        await session.execute(
            select(OrganizationOnboarding).where(
                OrganizationOnboarding.organization_id == org.id
            )
        )
    ).scalar_one_or_none()

    if completed is not None:
        status = "completed"
    elif len(missing) < len(_CHECKABLE_STEPS):
        # At least one step beyond registration is done -> in progress.
        status = "in_progress"
    else:
        # Nothing beyond registration is done yet -> still pending.
        status = "pending"

    # Re-establish contract order (the checks above append in a different order).
    ordered = [step for step in _STEP_ORDER if step in missing]
    return status, ordered


async def get_onboarding_status(
    session: AsyncSession, org: Organization
) -> OnboardingStatus:
    """Read-only onboarding status (GET /onboarding/status)."""
    status, missing = await compute_onboarding_status(session, org)
    return _to_schema(status, missing)


async def complete_onboarding(
    session: AsyncSession, org: Organization
) -> OnboardingCompleted | OnboardingIncomplete:
    """Mark onboarding complete when every mandatory step is satisfied.

    Returns ``OnboardingIncomplete`` (409) when any step is missing, carrying a
    cleaner body for the client. Returns ``OnboardingCompleted`` (200, with
    ``next="hive-mind-chat"``) once all steps are satisfied.

    Idempotent: if the org already has an ``OrganizationOnboarding`` row (a
    prior successful run, or a concurrent one that won the UNIQUE race), the
    existing ``completed`` state is returned without a second audit entry —
    completion is once per org.
    """
    status, missing = await compute_onboarding_status(session, org)
    if missing:
        return OnboardingIncomplete(
            onboardingStatus="in_progress", missingSteps=missing
        )

    existing = (
        await session.execute(
            select(OrganizationOnboarding).where(
                OrganizationOnboarding.organization_id == org.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return OnboardingCompleted()

    now = datetime.now(UTC)

    session.add(
        OrganizationOnboarding(
            tenant_id=org.tenant_id,
            organization_id=org.id,
            completed_at=now,
        )
    )
    session.add(
        AuditLog(
            tenant_id=org.tenant_id,
            action="onboarding.completed",
            actor_ref=None,
            payload={"organization_id": str(org.id)},
        )
    )
    await session.commit()

    return OnboardingCompleted()
