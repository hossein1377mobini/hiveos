"""Wallet endpoints (US-1203, T-S3-7)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend import wallet
from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/wallet")

_wallet_limiter = SlidingWindowLimiter(max_events=30, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_wallet_limiter)


class ChargeBody(BaseModel):
    # US-1203 AC2: quick-charge amounts (100/250/500/custom) in v0.1 mock pay.
    amount: int = Field(gt=0, le=100000)


@router.get("", dependencies=[Depends(_rate_limit)])
async def wallet_endpoint(
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-1203 AC1: balance + recent transactions (blocked flag for the banner).

    Also the caller's own consumption totals (PO requirement 2026-09).
    """
    return ok(await wallet.get_wallet_state(session, auth.organization.id, auth.user.id))


@router.post("/charge", dependencies=[Depends(_rate_limit)])
async def charge_endpoint(
    body: ChargeBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-1203 AC2: mock charge (payment gateway lands with US-1204 UI)."""
    return ok(await wallet.charge(session, auth.organization.id, body.amount))


class ChargeRequestBody(BaseModel):
    """T-S3-8 (zero-open loop): self-serve top-up request for admin approval."""

    amount: int = Field(gt=0, le=100000)
    note: str | None = Field(default=None, max_length=300)


@router.post("/charge-request", dependencies=[Depends(_rate_limit)], status_code=201)
async def charge_request_endpoint(
    body: ChargeRequestBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """User files a charge request; the System Admin approves it in the panel."""
    data = await wallet.create_charge_request(
        session, auth.organization.id, auth.user.id, body.amount, body.note
    )
    return ok(data)
