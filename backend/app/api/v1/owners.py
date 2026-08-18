"""US-002 Onboarding endpoints (v1): create the first Owner account.

Organization-scope resolution (v0.1): the request carries the pending
organization id in the ``X-Pending-Org`` header (the organization id returned by
POST /api/v1/organizations). This is used instead of a session cookie because at
this step no session exists yet — US-002 is precisely what issues the first
session. The header is treated as an unsigned scope hint valid only for
organizations still in ``pending_owner_registration`` (enforced in the service).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import NotFoundError, UnauthorizedError
from app.models import Organization
from app.schemas import OwnerCreate, OwnerCreated
from app.services import owner_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _resolve_pending_org_id(x_pending_org: str | None) -> UUID:
    if not x_pending_org or not x_pending_org.strip():
        raise UnauthorizedError("missing X-Pending-Org scope header")
    try:
        return UUID(x_pending_org.strip())
    except ValueError:
        raise UnauthorizedError("invalid X-Pending-Org scope header") from None


@router.post(
    "/users/owner",
    response_model=OwnerCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="createOwner",
    tags=["Onboarding"],
)
async def create_owner(
    data: OwnerCreate,
    response: Response,
    session: DbSession,
    x_pending_org: Annotated[str | None, Header()] = None,
) -> OwnerCreated:
    org_id = _resolve_pending_org_id(x_pending_org)

    pending_org = await session.get(Organization, org_id)
    if pending_org is None:
        raise NotFoundError("organization not found")

    owner, raw_token = await owner_service.create_owner(session, pending_org, data)

    # Secure HttpOnly session cookie scoping subsequent requests to the org.
    response.set_cookie(
        key="session",
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )

    return OwnerCreated(
        userId=owner.id,
        organizationId=owner.organization_id,
        status="pending",
        sessionIssued=True,
    )
