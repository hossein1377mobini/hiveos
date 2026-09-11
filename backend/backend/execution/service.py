"""Agent execution runtime, v0.1 minimal (US-301..306, T-S3-3).

Lifecycle: PENDING -> STARTING -> RUNNING -> COMPLETED, with
PENDING/STARTING/RUNNING -> FAILED and RUNNING -> CANCELLING ->
CANCELLED. The runtime cycle (US-306) produces a stub output here; the
real reasoning/retrieval/output steps land with T-S3-4.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import llm
from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.models import AgentExecution, ChatMessage, ChatSession, Organization

CANCELLABLE = ("PENDING", "STARTING", "RUNNING")
TERMINAL = ("CANCELLED", "COMPLETED", "FAILED")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _payload(execution: AgentExecution) -> dict:
    """US-301 §7 result contract."""
    return {
        "id": execution.id,
        "agent_id": execution.agent_id,
        "status": execution.status,
        "chat_session_id": execution.chat_session_id,
        "input": execution.input,
        "output": execution.output,
        "usage": execution.usage or {},
        "error": (
            {"code": execution.error_code, "message": execution.error_message}
            if execution.error_code
            else None
        ),
        "requested_by": execution.requested_by,
        "idempotency_key": execution.idempotency_key,
        "context_snapshot": execution.context_snapshot,
        "created_at": execution.created_at,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
    }


async def _chat_session_for(
    session: AsyncSession, organization_id, user_id, chat_session_id
) -> ChatSession | None:
    if chat_session_id is None:
        return None
    from backend.chat.service import authorize_session

    return await authorize_session(session, organization_id, user_id, chat_session_id)


async def create_execution(
    session: AsyncSession,
    organization_id,
    user_id,
    body: dict,
    idempotency_key: str | None = None,
) -> dict:
    """US-301/US-302: create a validated execution (idempotent replay)."""
    if idempotency_key:
        existing = (
            await session.execute(
                select(AgentExecution).where(
                    AgentExecution.organization_id == organization_id,
                    AgentExecution.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _payload(existing)

    # US-1207 (minimal subscription): an expired plan blocks new runs.
    org = await session.get(Organization, organization_id)
    if (
        org is not None
        and org.plan_expires_at is not None
        and org.plan_expires_at.astimezone(UTC) < datetime.now(UTC)
    ):
        raise ApiError(
            402,
            "SUBSCRIPTION_EXPIRED",
            "The organization plan has expired — extend it from the admin panel.",
        )

    # US-1203 AC7: the wallet gate fires before any online-model run.
    from backend import wallet

    await wallet.ensure_not_blocked(session, organization_id)

    chat_session_id = body.get("chat_session_id")
    chat = await _chat_session_for(session, organization_id, user_id, chat_session_id)
    input_payload = body.get("input") or {}
    text = str(input_payload.get("text", "")).strip()
    if not text:
        raise ApiError(400, "VALIDATION_ERROR", "input.text is required.")

    execution = AgentExecution(
        organization_id=organization_id,
        requested_by=user_id,
        agent_id=str(body.get("agent_id") or "hive-mind-default"),
        chat_session_id=chat.id if chat is not None else None,
        status="PENDING",
        input={"text": text[:32000]},
        idempotency_key=idempotency_key,
    )
    session.add(execution)
    await session.flush()
    await record_audit(
        session,
        "execution.created",
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="agent_execution",
        entity_id=execution.id,
        detail={"chat_session_id": str(chat_session_id) if chat_session_id else None},
    )
    return _payload(execution)


async def start_execution(
    session: AsyncSession, organization_id, user_id, execution_id
) -> dict:
    """US-303/US-304: PENDING -> STARTING -> RUNNING with context init."""
    execution = await get_execution_row(session, organization_id, execution_id)
    if execution.status != "PENDING":
        raise ApiError(409, "NOT_PENDING", f"Cannot start an execution in {execution.status}.")

    context: dict[str, Any] = {"message_count": 0}
    if execution.chat_session_id is not None:
        message_count = (
            await session.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.session_id == execution.chat_session_id)
            )
        ).scalar_one()
        context = {
            "message_count": message_count,
            "chat_session_id": str(execution.chat_session_id),
            "strategy": "TRUNCATE_OLDEST",
        }
    execution.context_snapshot = context
    execution.status = "RUNNING"
    execution.started_at = _utc_now()
    await record_audit(
        session,
        "execution.started",
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="agent_execution",
        entity_id=execution.id,
    )
    return _payload(execution)


async def run_cycle(session: AsyncSession, organization_id, execution_id) -> dict:
    """US-305..311: knowledge-retrieval cycle with mandatory citations.

    RG-07/Amendment 2: a knowledge-based answer carries citations; without
    retrieved evidence the answer says so and citations stay empty.
    """
    execution = await get_execution_row(session, organization_id, execution_id)
    if execution.status not in ("PENDING", "RUNNING"):
        raise ApiError(409, "NOT_RUNNING", f"Cannot run an execution in {execution.status}.")
    execution.status = "RUNNING"
    if execution.started_at is None:
        execution.started_at = _utc_now()

    # RG-18: basic prompt-injection sanitization on user input.
    query = llm.sanitize_prompt(str(execution.input.get("text", "")))
    try:
        from backend.knowledge.search import semantic_search

        results = await asyncio.wait_for(
            semantic_search(session, organization_id, query),
            timeout=get_settings().execution_timeout_seconds,
        )
        hits = results["results"]
    except TimeoutError:
        # US-314: the cycle is capped; a timed-out execution is FAILED.
        execution.error_code = "EXECUTION_TIMEOUT"
        execution.error_message = "The execution cycle exceeded its time budget."
        execution.status = "FAILED"
        execution.completed_at = _utc_now()
        await record_audit(
            session,
            "execution.failed",
            organization_id=organization_id,
            entity_type="agent_execution",
            entity_id=execution.id,
            detail={"error_code": "EXECUTION_TIMEOUT"},
        )
        return _payload(execution)
    except ApiError as error:  # e.g. EMBEDDING_UNAVAILABLE on the local provider
        execution.error_code = error.code
        execution.error_message = error.message
        execution.status = "FAILED"
        execution.completed_at = _utc_now()
        await record_audit(
            session,
            "execution.failed",
            organization_id=organization_id,
            entity_type="agent_execution",
            entity_id=execution.id,
            detail={"error_code": error.code},
        )
        return _payload(execution)

    context = ""
    if hits:
        citations = [
            {
                "doc_id": str(hit["asset_id"]),
                "title": hit["asset_name"],
                "snippet": hit["content"][:300],
            }
            for hit in hits
        ]
        context = "\n\n".join(
            f"[{index + 1}] {hit['asset_name']}: {hit['content']}"
            for index, hit in enumerate(hits)
        )
    else:
        citations = []

    # US-1202 (direct mode): the chat session's settings.model wins.
    requested_model = None
    if execution.chat_session_id is not None:
        chat = await session.get(ChatSession, execution.chat_session_id)
        if chat is not None:
            requested_model = (chat.settings or {}).get("model")
    model = await llm.aroute_model(session, requested_model)
    try:
        generated = await llm.agenerate(session, model, prompt=query, context=context)
    except ApiError as error:
        # US-313: aggregator/provider failures fail the execution cleanly.
        execution.error_code = error.code
        execution.error_message = error.message
        execution.status = "FAILED"
        execution.completed_at = _utc_now()
        await record_audit(
            session,
            "execution.failed",
            organization_id=organization_id,
            entity_type="agent_execution",
            entity_id=execution.id,
            detail={"error_code": error.code},
        )
        return _payload(execution)

    if hits:
        text = llm.mask_pii(f"بر اساس دانش سازمان:\n\n{context}\n\n{generated['text']}")
    else:
        text = llm.mask_pii("در دانش سازمان سند قابل‌استنادی یافت نشد؛ پاسخ بدون منبع است.\n\n" + generated["text"])

    # US-1201/1202 metering: usage rides on the execution row.
    execution.usage = {
        "provider": generated["provider"],
        "model": generated["model"],
        "tokens_in": generated["tokens_in"],
        "tokens_out": generated["tokens_out"],
    }
    # US-1203: atomic deduction after a successful online-model cycle.
    from backend import wallet as wallet_service

    await wallet_service.deduct_for_execution(
        session, organization_id, execution.id, generated["tokens_out"]
    )
    execution.output = {"text": text, "citations": citations}
    execution.status = "COMPLETED"
    execution.completed_at = _utc_now()
    await record_audit(
        session,
        "execution.completed",
        organization_id=organization_id,
        entity_type="agent_execution",
        entity_id=execution.id,
        detail={"citations": len(citations)},
    )
    # US-0909/RG-07: map the reply back into the originating chat session.
    if execution.chat_session_id is not None:
        from backend.chat.service import persist_assistant_reply

        await persist_assistant_reply(
            session,
            organization_id,
            execution.requested_by,
            execution.chat_session_id,
            text,
            citations=citations,
        )
    return _payload(execution)


async def cancel_execution(
    session: AsyncSession, organization_id, user_id, execution_id
) -> dict:
    """US-301: cancellation from PENDING/STARTING/RUNNING only."""
    execution = await get_execution_row(session, organization_id, execution_id)
    if execution.status in TERMINAL:
        raise ApiError(409, "ALREADY_TERMINAL", f"The execution is already {execution.status}.")
    if execution.status == "CANCELLING":
        raise ApiError(409, "ALREADY_CANCELLING", "Cancellation already in progress.")
    execution.status = "CANCELLING"
    execution.status = "CANCELLED"
    execution.completed_at = _utc_now()
    await record_audit(
        session,
        "execution.cancelled",
        organization_id=organization_id,
        actor_user_id=user_id,
        entity_type="agent_execution",
        entity_id=execution.id,
    )
    return _payload(execution)


async def get_execution_row(
    session: AsyncSession, organization_id, execution_id
) -> AgentExecution:
    execution = await session.get(AgentExecution, execution_id)
    if execution is None or execution.organization_id != organization_id:
        raise ApiError(404, "EXECUTION_NOT_FOUND", "Execution not found.")
    return execution


async def get_execution(session: AsyncSession, organization_id, execution_id) -> dict:
    return _payload(await get_execution_row(session, organization_id, execution_id))


async def list_executions(
    session: AsyncSession,
    organization_id,
    status: str = "ALL",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    conditions = [AgentExecution.organization_id == organization_id]
    if status != "ALL":
        conditions.append(AgentExecution.status == status)
    total = (
        await session.execute(
            select(func.count()).select_from(AgentExecution).where(*conditions)
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(AgentExecution)
                .where(*conditions)
                .order_by(AgentExecution.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_payload(row) for row in rows],
        "total_count": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }
