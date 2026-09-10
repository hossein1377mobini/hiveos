"""Knowledge source endpoints (US-007/US-201, dev-guidelines 4.2)."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.knowledge.service import get_source, register_folder_source, scan_source
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/knowledge-sources")

_knowledge_limiter = SlidingWindowLimiter(max_events=10, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_knowledge_limiter)


class KnowledgeSourceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=500)


@router.post("", dependencies=[Depends(_rate_limit)])
async def register_endpoint(
    payload: KnowledgeSourceCreate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-007 scenario 1: validate + register the ingestion folder."""
    result = await register_folder_source(session, auth.organization, payload.path)
    return ok(result)


@router.get("", dependencies=[Depends(_rate_limit)])
async def get_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db)
) -> dict:
    """US-007: the (single) knowledge source of the caller's organization."""
    result = await get_source(session, auth.organization)
    return ok(result if result is not None else {})


@router.post("/{source_id}/scan", dependencies=[Depends(_rate_limit)])
async def scan_endpoint(
    source_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-007 FR-006: Scan Now (initial scan summary until US-202 lands)."""
    result = await scan_source(session, auth.organization, source_id)
    return ok(result)
