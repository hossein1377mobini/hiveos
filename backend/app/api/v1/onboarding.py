"""US-008 Onboarding endpoints (v1): status check + one-time completion.

Protected by ``require_org_session`` (the US-002/US-003 session cookie) — the
resolved Organization is passed to the service, which derives progress across
US-001..US-005 + the US-007 folder watch and, on completion, marks onboarding
``completed`` exactly once.

Registered by the orchestrator in ``main.py`` — this module only defines the
router.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_org_session
from app.db import get_db
from app.models import Organization
from app.schemas import (
    OnboardingCompleted,
    OnboardingIncomplete,
    OnboardingStatus,
)
from app.services import onboarding_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]
OrgSession = Annotated[Organization, Depends(require_org_session)]


@router.get(
    "/onboarding/status",
    response_model=OnboardingStatus,
    status_code=status.HTTP_200_OK,
    operation_id="getOnboardingStatus",
    tags=["Onboarding"],
    responses={
        401: {"description": "سشن معتبر نیست"},
    },
)
async def get_onboarding_status(
    session: DbSession,
    org: OrgSession,
) -> OnboardingStatus:
    return await onboarding_service.get_onboarding_status(session, org)


@router.post(
    "/onboarding/complete",
    response_model=None,
    status_code=status.HTTP_200_OK,
    operation_id="completeOnboarding",
    tags=["Onboarding"],
    responses={
        200: {
            "description": "Onboarding تکمیل شد — handoff به Hive Mind chat",
            "content": {"application/json": {"schema": OnboardingCompleted.model_json_schema()}},
        },
        401: {"description": "سشن معتبر نیست"},
        409: {
            "description": "راه‌اندازی ناقص است — مراحل ناتمام",
            "content": {"application/json": {"schema": OnboardingIncomplete.model_json_schema()}},
        },
    },
)
async def complete_onboarding(
    session: DbSession,
    org: OrgSession,
) -> None:
    result = await onboarding_service.complete_onboarding(session, org)
    if isinstance(result, OnboardingIncomplete):
        return Response(
            status_code=status.HTTP_409_CONFLICT,
            content=result.model_dump_json(),
            media_type="application/json",
        )
    return OnboardingCompleted()
