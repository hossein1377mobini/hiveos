"""Semantic search endpoint (US-227, T-S2-6)."""


from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.knowledge.search import semantic_search
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/search")

_search_limiter = SlidingWindowLimiter(max_events=30, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_search_limiter)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


@router.post("", dependencies=[Depends(_rate_limit)])
async def search_endpoint(
    body: SearchBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-227: semantic search scoped to what the caller may read.

    The caller is passed through: results become the context of an AI answer, so
    an organization-only filter would feed a colleague's file into someone else's
    answer.
    """
    return ok(
        await semantic_search(
            session, auth.organization.id, body.query, body.top_k, auth.user.id
        )
    )
