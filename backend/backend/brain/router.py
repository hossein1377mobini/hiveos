"""Brain endpoints (US-005, dev-guidelines 4.2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.brain.service import initialize_brain
from backend.db import get_db
from backend.envelope import ok
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/brain")

_brain_limiter = SlidingWindowLimiter(max_events=10, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_brain_limiter)


@router.post("/initialize", dependencies=[Depends(_rate_limit)])
async def initialize_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """US-005 scenario 1: idempotent, transactional Brain bootstrap."""
    result = await initialize_brain(session, auth.organization)
    return ok(result)
