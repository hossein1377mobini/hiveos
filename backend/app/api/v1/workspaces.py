"""US-004 Onboarding endpoints (v1): initialize the organization Workspace.

Protected by ``require_org_session`` (US-002 / US-003 session cookie) — the
resolved Organization is passed to the service, which flips its single Workspace
to ``ready``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_org_session
from app.db import get_db
from app.models import Organization
from app.schemas import WorkspaceInitialized
from app.services import workspace_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/workspaces/initialize",
    response_model=WorkspaceInitialized,
    status_code=status.HTTP_201_CREATED,
    operation_id="initializeWorkspace",
    tags=["Onboarding"],
)
async def initialize_workspace(
    session: DbSession,
    org: Annotated[Organization, Depends(require_org_session)],
) -> WorkspaceInitialized:
    return await workspace_service.initialize_workspace(session, org)
