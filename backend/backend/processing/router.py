"""Processing job endpoints (US-203/US-214, dev-guidelines 4.2)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.knowledge.processing import cancel_job, get_job, list_jobs, retry_job
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/processing")

_processing_limiter = SlidingWindowLimiter(max_events=60, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_processing_limiter)


@router.get("/jobs", dependencies=[Depends(_rate_limit)])
async def list_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db)
) -> dict:
    """US-203: the caller's most recent processing jobs."""
    return ok({"jobs": await list_jobs(session, auth.organization)})


@router.get("/jobs/{job_id}", dependencies=[Depends(_rate_limit)])
async def get_endpoint(
    job_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-203: one job (tenant-isolated)."""
    return ok(await get_job(session, auth.organization, job_id))


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(_rate_limit)])
async def retry_endpoint(
    job_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-203 FR-008 / scenario 4: retry a failed job."""
    return ok(await retry_job(session, auth.organization, job_id))


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(_rate_limit)])
async def cancel_endpoint(
    job_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-214 (T-S2-3): cancel a queued/pending/retrying job."""
    return ok(await cancel_job(session, auth.organization, job_id))
