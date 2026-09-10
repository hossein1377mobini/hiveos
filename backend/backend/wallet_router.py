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
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-1203 AC1: balance + recent transactions (blocked flag for the banner)."""
    return ok(await wallet.get_wallet_state(session, auth.organization.id))


@router.post("/charge", dependencies=[Depends(_rate_limit)])
async def charge_endpoint(
    body: ChargeBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-1203 AC2: mock charge (payment gateway lands with US-1204 UI)."""
    return ok(await wallet.charge(session, auth.organization.id, body.amount))
