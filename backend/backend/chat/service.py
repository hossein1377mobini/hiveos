"""Chat session + message services (US-0901/US-0909, T-S3-1).

v0.1 scope: create/list/get/update-settings/archive/unarchive/soft-delete
for sessions (US-0901) and append-only messages with gap-less sequence +
idempotency + pagination (US-0909). Streaming/Agent execution land with
T-S3-2/3-4; hard delete/retention = US-0901 AC6 (v0.3 per US-216 pattern).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.models import AgentExecution, ChatMessage, ChatSession

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

# PO request 2026-09: "no session may be empty. If I create a new conversation
# and do nothing in it, delete it so it is not shown."
#
# The client opens a session speculatively (the "new chat" button calls
# POST /chat/sessions immediately, before anything is typed), so an abandoned
# session is a normal state, not an error. Two things are needed and they are
# not the same thing:
#
#   * the LIST must never show one - that is the visible half, and it is exact
#     (a live EXISTS on chat_messages, no reliance on a cached counter).
#   * the ROWS must not accumulate forever - that is the housekeeping half.
#
# The grace period exists only for housekeeping. A user who pressed "new chat"
# a second ago is about to type into that session; deleting it would make their
# send fail with CHAT_SESSION_NOT_FOUND. One hour is far beyond any realistic
# pause between opening a conversation and typing, and short enough that the
# table stays clean.
EMPTY_SESSION_GRACE = timedelta(hours=1)
# How many abandoned sessions one request may delete. Housekeeping must stay
# cheap: it runs inside the list request, and the backlog is bounded per call
# rather than by holding the request open until the table is empty.
EMPTY_SESSION_PURGE_LIMIT = 200

# How many earlier messages of a session are sent back to the model.
#
# The chat was stateless: agenerate() built [system, current question] on every
# call, so the model could not resolve a follow-up ("و دومی؟") and the only
# record that a conversation existed was the transcript on screen. The PO
# reported it as having no access to earlier sessions.
#
# 20 messages is ten exchanges. It is deliberately a message count rather than a
# token count: the per-session token_budget (128k) is far above what twenty
# Persian messages cost, so this bound keeps the prompt predictable and cheap
# without needing a tokenizer on this path. The oldest are dropped first, which
# is also the context_strategy the session settings name (TRUNCATE_OLDEST).
HISTORY_MESSAGES = 20


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
    payload = {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "citations": message.citations or [],
        "tokens": message.tokens,
        "sequence": message.sequence,
        "created_at": message.created_at,
    }
    # Only when there is something to say. A reply that created no file must
    # serialize exactly as it did before this field existed, so a client or a
    # test written against the old shape keeps working unchanged; an absent key
    # and an empty list both mean "no file", and the client reads it as such.
    if message.artifacts:
        payload["artifacts"] = message.artifacts
    return payload


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


async def authorize_session(
    session: AsyncSession, organization_id, user_id, session_id
) -> ChatSession:
    """Public authorization seam for the streaming endpoints (US-0902)."""
    chat = await _get_owned_session(session, organization_id, user_id, session_id)
    if chat.status != "ACTIVE":
        raise ApiError(409, "SESSION_NOT_ACTIVE", f"A {chat.status} session accepts no streams.")
    return chat


async def persist_assistant_reply(
    session: AsyncSession,
    organization_id,
    user_id,
    session_id,
    text: str,
    *,
    citations: list | None = None,
    artifacts: list | None = None,
) -> dict:
    """US-0902/US-0909: store the completed streamed reply as an ASSISTANT message.

    `artifacts` is the list of files this reply created, passed straight through
    to the same JSON column pattern citations use. Without it the file the agent
    just built is invisible the moment the user reloads the transcript.
    """
    return await append_message(
        session,
        organization_id,
        user_id,
        session_id,
        "ASSISTANT",
        {"text": text},
        citations=citations,
        artifacts=artifacts,
    )


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


async def load_history(
    session: AsyncSession,
    organization_id,
    user_id,
    chat_session_id,
    limit: int = HISTORY_MESSAGES,
) -> list[dict]:
    """The recent turns of one session, oldest first, for the model prompt.

    Scoped exactly like the transcript endpoint: the session must belong to this
    org and this user, so history can never become a way to read another user's
    conversation. Returns [] rather than raising when there is no session, so the
    caller can treat "no history" and "history failed" identically - both simply
    mean the model gets no prior turns.

    Reads from the same table the transcript renders, so what the model sees and
    what the user sees cannot drift apart.
    """
    if chat_session_id is None:
        return []
    owned = await session.execute(
        select(ChatSession.id).where(
            ChatSession.id == chat_session_id,
            ChatSession.organization_id == organization_id,
            ChatSession.owner_id == user_id,
        )
    )
    if owned.scalar_one_or_none() is None:
        return []
    rows = (
        (
            await session.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == chat_session_id,
                    ChatMessage.organization_id == organization_id,
                    ChatMessage.role.in_(("USER", "ASSISTANT")),
                )
                .order_by(ChatMessage.sequence.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    # The query walks backwards from the newest so LIMIT keeps the RECENT turns;
    # the prompt needs them the other way round.
    ordered = list(reversed(rows))
    history: list[dict] = []
    for message in ordered:
        content = (message.content or {}).get("text") if isinstance(message.content, dict) else None
        if content:
            history.append({"role": message.role, "content": str(content)})
    return history


async def purge_empty_sessions(
    session: AsyncSession, organization_id, user_id
) -> int:
    """Delete the caller's abandoned empty sessions (PO request 2026-09).

    Called from the list endpoint: that is exactly the moment the user is
    looking at their conversations, it is bounded (one statement, at most
    EMPTY_SESSION_PURGE_LIMIT rows), and it needs no scheduler - the audit noted
    the rows accumulating, and this is where anyone would notice them.

    Only the caller's own sessions, only zero-message ones, only older than
    EMPTY_SESSION_GRACE, so a session created seconds ago and about to receive
    the first message is untouched. Deleted hard, not soft: an abandoned empty
    row has no transcript to preserve, and keeping it as status='DELETED' would
    leave exactly the clutter the PO asked to remove.

    Returns the number of rows removed (0 when there is nothing to do).
    """
    cutoff = _utc_now() - EMPTY_SESSION_GRACE
    candidates = (
        select(ChatSession.id)
        .where(
            ChatSession.organization_id == organization_id,
            ChatSession.owner_id == user_id,
            ChatSession.created_at < cutoff,
            ~exists(
                select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id)
            ),
        )
        .order_by(ChatSession.created_at)
        .limit(EMPTY_SESSION_PURGE_LIMIT)
    )
    result = await session.execute(
        delete(ChatSession).where(ChatSession.id.in_(candidates))
    )
    return int(result.rowcount or 0)


async def list_sessions(
    session: AsyncSession, organization_id, user_id, filters: dict
) -> dict:
    """US-09.1.2: filtered + paginated list for the caller's own sessions."""
    status = filters.get("status", "ACTIVE")
    if status not in SESSION_STATUSES:
        raise ApiError(400, "VALIDATION_ERROR", "Unknown status filter.")
    page = max(int(filters.get("page", 1)), 1)
    page_size = min(max(int(filters.get("page_size", 20)), 1), MAX_PAGE_SIZE)

    # PO request 2026-09: an empty session must never surface.
    #
    # Done here, before anything else, so the purge cannot delete a row the
    # caller is about to be shown. One EXISTS per row, but no N+1: the correlated
    # subquery is inlined into the single COUNT/SELECT below, so the database
    # answers both in one statement each.
    await purge_empty_sessions(session, organization_id, user_id)

    conditions = [ChatSession.organization_id == organization_id]
    # The visible half of the same rule: a session with zero messages does not
    # exist as far as the user is concerned, whatever row lingers. Exact and
    # cheap - NOT context_state["message_count"], which is a cached counter that
    # a rolled-back append can leave stale.
    conditions.append(
        exists(
            select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id)
        )
    )
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

    # PO request 2026-09: "این تغییرات وضعیت‌ها باید آنلاین باشه" - the client must
    # be able to show, per conversation, whether an answer is being generated
    # right now, so it can offer a live status and let the user switch to another
    # chat while this one is still answering.
    #
    # This is a correlated EXISTS selected alongside the page, the same shape as
    # the message_count EXISTS above and for the same reason: ONE statement for
    # the whole page. A per-session lookup would be the classic N+1 and would
    # make the sidebar slower the more conversations the user has.
    #
    # `CANCELLABLE` is imported from the execution service rather than retyped
    # here, so the two can never disagree about which statuses mean "live".
    from backend.execution.service import CANCELLABLE

    generating = exists(
        select(AgentExecution.id).where(
            AgentExecution.chat_session_id == ChatSession.id,
            # Belt and braces: chat_session_id is globally unique, so the org
            # predicate can never match a row outside this tenant. It is stated
            # anyway because every read path here carries the tenant boundary.
            AgentExecution.organization_id == organization_id,
            AgentExecution.status.in_(CANCELLABLE),
        )
    )
    rows = (
        await session.execute(
            select(ChatSession, generating.label("generating"))
            .where(*conditions)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = []
    for chat, is_generating in rows:
        items.append(
            {
                "id": chat.id,
                "title": chat.title,
                "status": chat.status,
                "message_count": (chat.context_state or {}).get("message_count", 0),
                "current_token_count": (chat.context_state or {}).get(
                    "current_token_count", 0
                ),
                "generating": bool(is_generating),
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
    # S9 (external review): serialize concurrent PATCHes on the session row;
    # the version check then compares against the post-lock value.
    await session.execute(
        select(ChatSession.id).where(ChatSession.id == chat.id).with_for_update()
    )
    await session.refresh(chat)
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
    artifacts: list | None = None,
    tokens: int = 0,
    idempotency_key: str | None = None,
    parent_id=None,
) -> dict:
    """US-0909 FR: append-only message with gap-less sequence.

    US-09.9.1: role=USER comes from the API; ASSISTANT/SYSTEM/TOOL messages
    are written by internal services (T-S3-4). Citations are valid only on
    ASSISTANT messages (RG-07); artifacts follow the same rule, because they
    are the same kind of fact - structured provenance for one reply.
    """
    if role not in MESSAGE_ROLES:
        raise ApiError(400, "VALIDATION_ERROR", "Unknown message role.")
    if citations and role != "ASSISTANT":
        raise ApiError(400, "CITATIONS_NOT_ALLOWED", "Citations are only valid on ASSISTANT messages.")
    if artifacts and role != "ASSISTANT":
        raise ApiError(
            400, "ARTIFACTS_NOT_ALLOWED", "Artifacts are only valid on ASSISTANT messages."
        )

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

    # S3 (external review): lock the session row so two concurrent messages
    # cannot read the same MAX(sequence) and collide on the unique index.
    await session.execute(
        select(ChatSession.id).where(ChatSession.id == chat.id).with_for_update()
    )
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
        artifacts=artifacts or None,
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
