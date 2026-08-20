"""US-001 Onboarding endpoints (v1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import enforce_registration_ip_limit
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
    response: Response,
    _rate: Annotated[None, Depends(enforce_registration_ip_limit)],
) -> Organization:
    org, onboard_token = await organization_service.create_organization(session, data)

    # F-2: bind owner creation to this browser via a proof-of-possession
    # onboarding cookie (HttpOnly) — not a client-forgeable scope header.
    response.set_cookie(
        key="onboarding",
        value=onboard_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )

    return Organization(
        id=org.id,
        name=org.display_name,
        status=org.status,
        tenantId=org.tenant_id,
        workspaceId=org.workspace_id,
        createdAt=org.created_at,
    )
