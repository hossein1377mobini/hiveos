"""US-002 Onboarding endpoints (v1): create the first Owner account.

Organization-scope resolution (F-2 hardening): the request is scoped by the
HttpOnly ``onboarding`` cookie issued when the Organization was created in
US-001 (proof of possession). The previous client-supplied ``X-Pending-Org``
header is removed — it was forgeable and unsafe as a trust boundary. The
onboarding cookie is accepted only for organizations still in
``pending_owner_registration`` (enforced in the service via
``resolve_pending_org_by_onboard_token``).
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import OwnerCreate, OwnerCreated
from app.services import organization_service, owner_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


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
    onboarding: Annotated[str | None, Cookie()] = None,
) -> OwnerCreated:
    pending_org = await organization_service.resolve_pending_org_by_onboard_token(
        session, onboarding
    )

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
