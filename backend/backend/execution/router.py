"""Agent execution endpoints (US-301..306, T-S3-3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.execution import service
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/executions")

_execution_limiter = SlidingWindowLimiter(max_events=60, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_execution_limiter)


class CreateExecutionBody(BaseModel):
    # US-09.9.1/US-301: input text is required; chat_session_id optional.
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, max_length=100)
    chat_session_id: uuid.UUID | None = None
    input: dict = Field(default_factory=dict)


@router.post("", dependencies=[Depends(_rate_limit)])
async def create_execution_endpoint(
    body: CreateExecutionBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict:
    """US-301: create a validated execution (idempotent via header)."""
    return ok(
        await service.create_execution(
            session,
            auth.organization.id,
            auth.user.id,
            body.model_dump(),
            idempotency_key=idempotency_key,
        )
    )


@router.get("", dependencies=[Depends(_rate_limit)])
async def list_executions_endpoint(
    status: str = "ALL",
    page: int = 1,
    page_size: int = 20,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-301: org-isolated, filterable execution list."""
    return ok(
        await service.list_executions(
            session, auth.organization.id, status=status, page=page, page_size=page_size
        )
    )


@router.get("/{execution_id}", dependencies=[Depends(_rate_limit)])
async def get_execution_endpoint(
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-301: execution details (result contract)."""
    return ok(await service.get_execution(session, auth.organization.id, execution_id))


@router.post("/{execution_id}/start", dependencies=[Depends(_rate_limit)])
async def start_execution_endpoint(
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-303/304: start the execution and initialize its context."""
    return ok(
        await service.start_execution(
            session, auth.organization.id, auth.user.id, execution_id
        )
    )


@router.post("/{execution_id}/run", dependencies=[Depends(_rate_limit)])
async def run_cycle_endpoint(
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-305/306: run the (minimal) runtime cycle to completion."""
    return ok(await service.run_cycle(session, auth.organization.id, execution_id))


@router.post("/{execution_id}/cancel", dependencies=[Depends(_rate_limit)])
async def cancel_execution_endpoint(
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-301: cancel a non-terminal execution."""
    return ok(
        await service.cancel_execution(
            session, auth.organization.id, auth.user.id, execution_id
        )
    )
