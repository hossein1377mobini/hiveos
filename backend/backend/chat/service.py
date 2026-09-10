"""Chat session + message services (US-0901/US-0909, T-S3-1).

v0.1 scope: create/list/get/update-settings/archive/unarchive/soft-delete
for sessions (US-0901) and append-only messages with gap-less sequence +
idempotency + pagination (US-0909). Streaming/Agent execution land with
T-S3-2/3-4; hard delete/retention = US-0901 AC6 (v0.3 per US-216 pattern).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.models import ChatMessage, ChatSession

SESSION_STATUSES = ("ACTIVE", "ARCHIVED", "DELETED", "ALL")
MESSAGE_ROLES = ("USER", "ASSISTANT", "SYSTEM", "TOOL")

DEFAULT_SETTINGS = {
    "model": "hive-mind-default",
    "temperature": 0.7,
    "system_prompt_id": None,  # US-1609 template resolution lands in T-S3-4
    "context_strategy": "TRUNCATE_OLDEST",
    "token_budget": 128000,
    "auto_summarize_threshold": 0.8,
    "retention_days": None,
}

MAX_PAGE_SIZE = 100


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _settings_payload(session: ChatSession) -> dict:
    merged = {**DEFAULT_SETTINGS, **(session.settings or {})}
    return merged


def _session_payload(session: ChatSession, message_count: int | None = None) -> dict:
    context_state = session.context_state or {}
    return {
        "id": session.id,
        "title": session.title,
        "description": session.description,
        "status": session.status,
        "settings": _settings_payload(session),
        "context_state": {
            **context_state,
            "message_count": context_state.get("message_count", message_count or 0),
        },
        "tags": session.tags or [],
        "pinned": session.pinned,
        "version": session.version,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "archived_at": session.archived_at,
        "deleted_at": session.deleted_at,
    }


def _message_payload(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "citations": message.citations or [],
        "tokens": message.tokens,
        "sequence": message.sequence,
        "created_at": message.created_at,
    }


async def _get_owned_session(
    session: AsyncSession, organization_id, user_id, session_id
) -> ChatSession:
    """US-09.1.3 authorization: owner or shared_with (org Admin in v0.1 = owner)."""
    chat = await session.get(ChatSession, session_id)
    if chat is None or chat.organization_id != organization_id:
        raise ApiError(404, "CHAT_SESSION_NOT_FOUND", "Chat session not found.")
    shared = chat.context_state.get("shared_with", []) if chat.context_state else []
    if chat.owner_id != user_id and str(user_id) not in [str(s) for s in shared]:
        raise ApiError(404, "CHAT_SESSION_NOT_FOUND", "Chat session not found.")
    return chat


async def create_session(
    session: AsyncSession, organization_id, user_id, body: dict
) -> dict:
    """US-09.1.1: create a session with defaults inherited from settings."""
    title = (body.get("title") or "").strip()[:200]
    description = body.get("description")
    settings = dict(DEFAULT_SETTINGS)
    incoming = body.get("settings") or {}
    if incoming.get("temperature") is not None:
        temperature = float(incoming["temperature"])
        if not 0.0 <= temperature <= 2.0:
            raise ApiError(400, "VALIDATION_ERROR", "temperature must be within 0.0 and 2.0.")
        settings["temperature"] = temperature
    if incoming.get("token_budget") is not None:
        budget = int(incoming["token_budget"])
        if budget <= 0:
            raise ApiError(400, "VALIDATION_ERROR", "token_budget must be positive.")
        settings["token_budget"] = budget
    if incoming.get("model"):
        settings["model"] = str(incoming["model"])
    if incoming.get("context_strategy"):
        if incoming["context_strategy"] not in ("TRUNCATE_OLDEST", "SUMMARIZE", "SELECTIVE"):
            raise ApiError(400, "VALIDATION_ERROR", "Unknown context_strategy.")
        settings["context_strategy"] = incoming["context_strategy"]

    chat = ChatSession(
        organization_id=organization_id,
        owner_id=user_id,
        title=title,
        description=(description or "")[:2000] if description else None,
        status="ACTIVE",
        settings=settings,
        context_state={"shared_with": [], "message_count": 0, "current_token_count": 0},
        tags=(body.get("tags") or [])[:20],
        pinned=bool(body.get("pinned", False)),
    )
    session.add(chat)
    await session.flush()
    await record_audit(
        session,
        "chat-session.created",
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="chat_session",
        entity_id=chat.id,
    )
    return _session_payload(chat, 0)


async def list_sessions(
    session: AsyncSession, organization_id, user_id, filters: dict
) -> dict:
    """US-09.1.2: filtered + paginated list for the caller's own sessions."""
    status = filters.get("status", "ACTIVE")
    if status not in SESSION_STATUSES:
        raise ApiError(400, "VALIDATION_ERROR", "Unknown status filter.")
    page = max(int(filters.get("page", 1)), 1)
    page_size = min(max(int(filters.get("page_size", 20)), 1), MAX_PAGE_SIZE)

    conditions = [ChatSession.organization_id == organization_id]
    if status != "ALL":
        conditions.append(ChatSession.status == status)
    conditions.append(ChatSession.owner_id == user_id)
    search = (filters.get("search") or "").strip()
    if search:
        pattern = f"%{search.lower()}%"
        conditions.append(
            func.lower(ChatSession.title).like(pattern)
            | func.lower(func.coalesce(ChatSession.description, "")).like(pattern)
        )
    pinned = filters.get("pinned")
    if pinned in ("true", True):
        conditions.append(ChatSession.pinned.is_(True))
    elif pinned in ("false", False):
        conditions.append(ChatSession.pinned.is_(False))

    total = (
        await session.execute(
            select(func.count()).select_from(ChatSession).where(*conditions)
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(ChatSession)
                .where(*conditions)
                .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = []
    for chat in rows:
        items.append(
            {
                "id": chat.id,
                "title": chat.title,
                "status": chat.status,
                "message_count": (chat.context_state or {}).get("message_count", 0),
                "current_token_count": (chat.context_state or {}).get(
                    "current_token_count", 0
                ),
                "updated_at": chat.updated_at,
                "pinned": chat.pinned,
                "tags": chat.tags or [],
                "last_message_preview": (chat.context_state or {}).get(
                    "last_message_preview", ""
                ),
            }
        )
    return {
        "items": items,
        "total_count": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


async def get_session(
    session: AsyncSession, organization_id, user_id, session_id
) -> dict:
    """US-09.1.3: session details (404 also for deleted sessions)."""
    chat = await _get_owned_session(session, organization_id, user_id, session_id)
    if chat.status == "DELETED":
        raise ApiError(404, "CHAT_SESSION_NOT_FOUND", "Chat session not found.")
    count = (
        await session.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.session_id == chat.id)
        )
    ).scalar_one()
    return _session_payload(chat, count)


async def update_settings(
    session: AsyncSession, organization_id, user_id, session_id, body: dict, expected_version: int | None
) -> dict:
    """US-09.1.4: PATCH settings with optimistic locking via version."""
    chat = await _get_owned_session(session, organization_id, user_id, session_id)
    if chat.status == "DELETED":
        raise ApiError(404, "CHAT_SESSION_NOT_FOUND", "Chat session not found.")
    if expected_version is not None and expected_version != chat.version:
        raise ApiError(409, "VERSION_CONFLICT", "The session was modified concurrently.")

    settings = _settings_payload(chat)
    if body.get("temperature") is not None:
        temperature = float(body["temperature"])
        if not 0.0 <= temperature <= 2.0:
            raise ApiError(400, "VALIDATION_ERROR", "temperature must be within 0.0 and 2.0.")
        settings["temperature"] = temperature
    if body.get("token_budget") is not None:
        budget = int(body["token_budget"])
        if budget <= 0:
            raise ApiError(400, "VALIDATION_ERROR", "token_budget must be positive.")
        settings["token_budget"] = budget
    if body.get("model"):
        settings["model"] = str(body["model"])
    if body.get("context_strategy"):
        if body["context_strategy"] not in ("TRUNCATE_OLDEST", "SUMMARIZE", "SELECTIVE"):
            raise ApiError(400, "VALIDATION_ERROR", "Unknown context_strategy.")
        settings["context_strategy"] = body["context_strategy"]
    if "system_prompt_id" in body:
        settings["system_prompt_id"] = body["system_prompt_id"]

    chat.settings = settings
    chat.version += 1
    chat.updated_at = _utc_now()
    await record_audit(
        session,
        "chat-session.settings_updated",
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="chat_session",
        entity_id=chat.id,
        detail={"version": chat.version},
    )
    return _session_payload(chat)


async def archive_session(
    session: AsyncSession, organization_id, user_id, session_id, archive: bool
) -> dict:
    """US-09.1.5: archive/unarchive (ACTIVE <-> ARCHIVED only)."""
    chat = await _get_owned_session(session, organization_id, user_id, session_id)
    if chat.status == "DELETED":
        raise ApiError(404, "CHAT_SESSION_NOT_FOUND", "Chat session not found.")
    if archive and chat.status == "ARCHIVED":
        raise ApiError(409, "ALREADY_ARCHIVED", "The session is already archived.")
    if not archive and chat.status == "ACTIVE":
        raise ApiError(409, "NOT_ARCHIVED", "The session is not archived.")
    chat.status = "ARCHIVED" if archive else "ACTIVE"
    chat.archived_at = _utc_now() if archive else None
    chat.version += 1
    event = "chat-session.archived" if archive else "chat-session.unarchived"
    await record_audit(
        session,
        event,
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="chat_session",
        entity_id=chat.id,
    )
    return _session_payload(chat)


async def delete_session(
    session: AsyncSession, organization_id, user_id, session_id
) -> dict:
    """US-09.1.6 (v0.1): soft delete only; hard delete/retention = later."""
    chat = await _get_owned_session(session, organization_id, user_id, session_id)
    if chat.status == "DELETED":
        return {"id": chat.id, "deleted": True}
    chat.status = "DELETED"
    chat.deleted_at = _utc_now()
    chat.version += 1
    await record_audit(
        session,
        "chat-session.deleted",
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="chat_session",
        entity_id=chat.id,
    )
    return {"id": chat.id, "deleted": True}


async def append_message(
    session: AsyncSession,
    organization_id,
    user_id,
    session_id,
    role: str,
    content: dict,
    *,
    citations: list | None = None,
    tokens: int = 0,
    idempotency_key: str | None = None,
    parent_id=None,
) -> dict:
    """US-0909 FR: append-only message with gap-less sequence.

    US-09.9.1: role=USER comes from the API; ASSISTANT/SYSTEM/TOOL messages
    are written by internal services (T-S3-4). Citations are valid only on
    ASSISTANT messages (RG-07).
    """
    if role not in MESSAGE_ROLES:
        raise ApiError(400, "VALIDATION_ERROR", "Unknown message role.")
    if citations and role != "ASSISTANT":
        raise ApiError(400, "CITATIONS_NOT_ALLOWED", "Citations are only valid on ASSISTANT messages.")

    chat = await _get_owned_session(session, organization_id, user_id, session_id)
    if chat.status != "ACTIVE":
        raise ApiError(409, "SESSION_NOT_ACTIVE", f"A {chat.status} session accepts no messages.")

    if idempotency_key:
        existing_meta = ChatMessage.message_metadata
        duplicate = (
            await session.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == chat.id,
                    existing_meta["idempotency_key"].as_string() == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            return _message_payload(duplicate)

    last_sequence = (
        await session.execute(
            select(func.coalesce(func.max(ChatMessage.sequence), 0)).where(
                ChatMessage.session_id == chat.id
            )
        )
    ).scalar_one()
    message = ChatMessage(
        organization_id=organization_id,
        session_id=chat.id,
        role=role,
        content=content,
        citations=citations,
        tokens=tokens,
        message_metadata={"idempotency_key": idempotency_key} if idempotency_key else {},
        parent_id=parent_id,
        sequence=last_sequence + 1,
    )
    session.add(message)
    await session.flush()  # assign id/created_at before building the payload

    context_state = dict(chat.context_state or {})
    context_state["message_count"] = int(context_state.get("message_count", 0)) + 1
    if role == "USER" and not chat.title:
        text_value = str(content.get("text", "")).strip()
        if text_value:
            chat.title = text_value[:200]
    if role == "USER":
        preview = str(content.get("text", ""))[:100]
        context_state["last_message_preview"] = preview
    chat.context_state = context_state
    chat.updated_at = _utc_now()

    await record_audit(
        session,
        "chat-message.created",
        organization_id=organization_id,
        actor_user_id=user_id if role == "USER" else None,
        entity_type="chat_message",
        entity_id=message.id,
        detail={"role": role, "session_id": str(chat.id)},
    )
    return _message_payload(message)


async def list_messages(
    session: AsyncSession,
    organization_id,
    user_id,
    session_id,
    *,
    order: str = "asc",
    page: int = 1,
    page_size: int = 50,
    before: int | None = None,
    after: int | None = None,
) -> dict:
    """US-09.9.2: paginated history with optional sequence cursors."""
    if order not in ("asc", "desc"):
        raise ApiError(400, "VALIDATION_ERROR", "order must be asc or desc.")
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    chat = await _get_owned_session(session, organization_id, user_id, session_id)

    conditions = [ChatMessage.session_id == chat.id]
    if before is not None:
        conditions.append(ChatMessage.sequence < before)
    if after is not None:
        conditions.append(ChatMessage.sequence > after)

    total = (
        await session.execute(
            select(func.count()).select_from(ChatMessage).where(*conditions)
        )
    ).scalar_one()
    query = (
        select(ChatMessage)
        .where(*conditions)
        .order_by(
            ChatMessage.sequence.desc() if order == "desc" else ChatMessage.sequence.asc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(query)).scalars().all()
    items = [_message_payload(row) for row in rows]
    return {
        "items": items,
        "total_count": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }
