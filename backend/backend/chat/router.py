"""Chat session + message endpoints (US-0901/US-0909, T-S3-1)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.chat import service
from backend.db import get_db
from backend.envelope import ok
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/chat")

_chat_limiter = SlidingWindowLimiter(max_events=60, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_chat_limiter)


class CreateSessionBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    pinned: bool = False
    settings: dict | None = None


class SettingsBody(BaseModel):
    model: str | None = Field(default=None, max_length=100)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    system_prompt_id: uuid.UUID | str | None = None
    context_strategy: str | None = None
    token_budget: int | None = Field(default=None, gt=0)
    auto_summarize_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    retention_days: int | None = Field(default=None, ge=1)
    expected_version: int | None = Field(default=None, ge=1)


class SendMessageBody(BaseModel):
    # US-09.9.1: citations belong to ASSISTANT messages (RG-07) — a USER
    # payload carrying them is rejected outright.
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=32000)


@router.post("/sessions", dependencies=[Depends(_rate_limit)])
async def create_session_endpoint(
    body: CreateSessionBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.1: create a chat session."""
    return ok(
        await service.create_session(
            session, auth.organization.id, auth.user.id, body.model_dump()
        )
    )


@router.get("/sessions", dependencies=[Depends(_rate_limit)])
async def list_sessions_endpoint(
    status: str = "ACTIVE",
    search: str = "",
    pinned: str = "all",
    page: int = 1,
    page_size: int = 20,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.2: filtered, paginated session list."""
    return ok(
        await service.list_sessions(
            session,
            auth.organization.id,
            auth.user.id,
            {
                "status": status,
                "search": search,
                "pinned": pinned,
                "page": page,
                "page_size": page_size,
            },
        )
    )


@router.get("/sessions/{session_id}", dependencies=[Depends(_rate_limit)])
async def get_session_endpoint(
    session_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.3: session details (404 for deleted)."""
    return ok(
        await service.get_session(session, auth.organization.id, auth.user.id, session_id)
    )


@router.patch("/sessions/{session_id}/settings", dependencies=[Depends(_rate_limit)])
async def update_settings_endpoint(
    session_id: uuid.UUID,
    body: SettingsBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.4: update session settings (optimistic lock)."""
    return ok(
        await service.update_settings(
            session,
            auth.organization.id,
            auth.user.id,
            session_id,
            body.model_dump(exclude_none=False),
            body.expected_version,
        )
    )


@router.post("/sessions/{session_id}/archive", dependencies=[Depends(_rate_limit)])
async def archive_endpoint(
    session_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.5: archive a session."""
    return ok(
        await service.archive_session(
            session, auth.organization.id, auth.user.id, session_id, True
        )
    )


@router.post("/sessions/{session_id}/unarchive", dependencies=[Depends(_rate_limit)])
async def unarchive_endpoint(
    session_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.5: unarchive a session."""
    return ok(
        await service.archive_session(
            session, auth.organization.id, auth.user.id, session_id, False
        )
    )


@router.delete("/sessions/{session_id}", dependencies=[Depends(_rate_limit)])
async def delete_session_endpoint(
    session_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.1.6 (v0.1): soft delete."""
    return ok(
        await service.delete_session(session, auth.organization.id, auth.user.id, session_id)
    )


@router.post("/sessions/{session_id}/messages", dependencies=[Depends(_rate_limit)])
async def send_message_endpoint(
    session_id: uuid.UUID,
    body: SendMessageBody,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict:
    """US-09.9.1: append a USER message (Agent reply lands via T-S3-4)."""
    return ok(
        await service.append_message(
            session,
            auth.organization.id,
            auth.user.id,
            session_id,
            "USER",
            {"text": body.text},
            idempotency_key=idempotency_key,
        )
    )


@router.get("/sessions/{session_id}/messages", dependencies=[Depends(_rate_limit)])
async def list_messages_endpoint(
    session_id: uuid.UUID,
    order: str = "asc",
    page: int = 1,
    page_size: int = 50,
    before: int | None = None,
    after: int | None = None,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-09.9.2: paginated message history."""
    return ok(
        await service.list_messages(
            session,
            auth.organization.id,
            auth.user.id,
            session_id,
            order=order,
            page=page,
            page_size=page_size,
            before=before,
            after=after,
        )
    )
