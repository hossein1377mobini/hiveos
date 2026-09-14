"""Workspace endpoints (US-004, dev-guidelines 4.2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency
from backend.workspace.service import initialize_workspace

router = APIRouter(prefix="/workspaces")

# Org-scoped mutations: same per-IP policy as the bootstrap endpoints.
_workspace_limiter = SlidingWindowLimiter(max_events=10, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_workspace_limiter)


@router.post("/initialize", dependencies=[Depends(_rate_limit)])
async def initialize_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """US-004 scenario 1: idempotent initialization of the primary workspace."""
    result = await initialize_workspace(session, auth.organization)
    return ok(result)
