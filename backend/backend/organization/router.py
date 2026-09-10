"""Bootstrap endpoints (dev-guidelines §۴.۲): /api/v1/auth/....

- POST /api/v1/auth/register-organization  (US-001 merged path)
- POST /api/v1/auth/owner                  (US-002)
- GET  /api/v1/auth/username-available     (owner form live check)

Responses use the {success, data, message} envelope (API Design Standards).
Errors raise ApiError -> {success:false, error:{code,message}}.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.organization.schemas import (
    OrganizationCreated,
    OwnerCreated,
    RegisterOrganizationRequest,
    RegisterOwnerRequest,
    UsernameAvailability,
)
from backend.organization.service import register_organization, register_owner, username_available
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/auth")

# Per-IP limiter for unauthenticated bootstrap endpoints (US-001/002 security).
_auth_limiter = SlidingWindowLimiter(max_events=10, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_auth_limiter)


def _ok(data: dict) -> dict:
    return {"success": True, "data": data, "message": None}


@router.post("/register-organization", dependencies=[Depends(_rate_limit)])
async def create_organization(
    payload: RegisterOrganizationRequest, session: AsyncSession = Depends(get_db)
) -> dict:
    """US-001 scenario 1: create organization + workspace, then redirect to owner step."""
    result = await register_organization(session, payload)
    created = OrganizationCreated(**result)
    return _ok(created.model_dump(mode="json"))


@router.post("/owner", dependencies=[Depends(_rate_limit)])
async def create_owner(
    payload: RegisterOwnerRequest, session: AsyncSession = Depends(get_db)
) -> dict:
    """US-002 scenario 1: create owner account, assign role, issue initial session."""
    result = await register_owner(session, payload)
    created = OwnerCreated(**result)
    return _ok(created.model_dump(mode="json"))


@router.get("/username-available")
async def check_username(
    username: str = Query(min_length=1, max_length=50),
    session: AsyncSession = Depends(get_db),
) -> dict:
    result = await username_available(session, username)
    checked = UsernameAvailability(**result)
    return _ok(checked.model_dump(mode="json"))
