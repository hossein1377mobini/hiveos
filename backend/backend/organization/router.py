"""Bootstrap endpoints (dev-guidelines §۴.۲): /api/v1/auth/....

- POST /api/v1/auth/register-organization  (US-001 merged path)
- POST /api/v1/auth/owner                  (US-002)
- GET  /api/v1/auth/username-available     (owner form live check)
- POST /api/v1/auth/send-otp               (US-003, Bearer session required)
- POST /api/v1/auth/resend-otp             (US-003, same state machine)
- POST /api/v1/auth/verify-otp             (US-003, T-S1-4: activation + slid session)

Responses use the {success, data, message} envelope (API Design Standards).
Errors raise ApiError -> {success:false, error:{code,message}}.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.organization.otp_service import PURPOSE_OWNER_VERIFICATION, send_otp
from backend.organization.otp_verify import verify_otp
from backend.organization.schemas import (
    OrganizationCreated,
    OtpSent,
    OtpVerified,
    OwnerCreated,
    RegisterOrganizationRequest,
    RegisterOwnerRequest,
    UsernameAvailability,
    VerifyOtpRequest,
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


@router.post("/send-otp", dependencies=[Depends(_rate_limit)])
async def send_otp_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db)
) -> dict:
    """US-003 scenario 1: send the owner-verification OTP to the session user's mobile."""
    result = await send_otp(
        session, auth.user, purpose=PURPOSE_OWNER_VERIFICATION, event="otp.sent"
    )
    sent = OtpSent(**result)
    return _ok(sent.model_dump(mode="json"))


@router.post("/resend-otp", dependencies=[Depends(_rate_limit)])
async def resend_otp_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db)
) -> dict:
    """US-003 scenario 3: resend after cooldown / expiry; new code invalidates the old one."""
    result = await send_otp(
        session, auth.user, purpose=PURPOSE_OWNER_VERIFICATION, event="otp.resent"
    )
    sent = OtpSent(**result)
    return _ok(sent.model_dump(mode="json"))


@router.post("/verify-otp", dependencies=[Depends(_rate_limit)])
async def verify_otp_endpoint(
    payload: VerifyOtpRequest,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-003 FR-003: activate owner + organization; session slides to a fresh TTL."""
    result = await verify_otp(session, auth.user, auth.organization, payload.code)
    verified = OtpVerified(
        user_id=auth.user.id,
        organization_id=auth.organization.id,
        organization_status=result["organization_status"],
        session={"token": auth.token, "expires_at": auth.session.expires_at},
    )
    return _ok(verified.model_dump(mode="json"))
