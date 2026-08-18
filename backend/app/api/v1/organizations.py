"""US-001 Onboarding endpoints (v1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import Organization, OrganizationCreate
from app.services import organization_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/organizations",
    response_model=Organization,
    status_code=status.HTTP_201_CREATED,
    operation_id="createOrganization",
    tags=["Onboarding"],
)
async def create_organization(
    data: OrganizationCreate,
    session: DbSession,
) -> Organization:
    org = await organization_service.create_organization(session, data)
    return Organization(
        id=org.id,
        name=org.display_name,
        status=org.status,
        tenantId=org.tenant_id,
        workspaceId=org.workspace_id,
        createdAt=org.created_at,
    )
