"""US-005 Onboarding endpoint (v1): initialize the baseline Organization Brain."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_org_session
from app.db import get_db
from app.models import Organization
from app.schemas import BrainInitialized
from app.services import brain_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/brain/initialize",
    response_model=BrainInitialized,
    status_code=status.HTTP_201_CREATED,
    operation_id="initializeBrain",
    tags=["Onboarding"],
    responses={
        401: {"description": "سشن معتبر نیست"},
        409: {"description": "تعارض — سازمان فعال نیست / Workspace آماده نیست"},
        500: {"description": "راهاندازی ناموفق (audit-logged) — retry مجاز"},
    },
)
async def initialize_brain(
    session: DbSession,
    org: Annotated[Organization, Depends(require_org_session)],
) -> BrainInitialized:
    return await brain_service.initialize_brain(session, org)
