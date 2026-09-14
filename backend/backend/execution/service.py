"""Agent execution runtime, v0.1 minimal (US-301..306, T-S3-3).

Lifecycle: PENDING -> STARTING -> RUNNING -> COMPLETED, with
PENDING/STARTING/RUNNING -> FAILED and RUNNING -> CANCELLING ->
CANCELLED. The runtime cycle (US-306) produces a stub output here; the
real reasoning/retrieval/output steps land with T-S3-4.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import llm
from backend.api_errors import ApiError
from backend.audit import record_audit, record_audit_durable
from backend.config import get_settings
from backend.models import (
    AgentExecution,
    AgentToolInvocation,
    ChatMessage,
    ChatSession,
    Organization,
)

logger = logging.getLogger(__name__)

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
    # D3: row lock so two concurrent /run calls cannot both pass the status
    # check and bill the wallet twice for one execution.
    execution = (
        await session.execute(
            select(AgentExecution)
            .where(AgentExecution.id == execution_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if execution is None or execution.organization_id != organization_id:
        raise ApiError(404, "EXECUTION_NOT_FOUND", "Execution not found.")
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
        await record_audit_durable(
            "execution.failed",
            organization_id=organization_id,
            actor_user_id=execution.requested_by,
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
        await record_audit_durable(
            "execution.failed",
            organization_id=organization_id,
            actor_user_id=execution.requested_by,
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

    # --- Per-user agent (PO 2026-09) ---------------------------------------
    # Everything below is additive: this user's agent, their recalled memories,
    # and the tool loop. If any of it fails the answer is still produced, because
    # a memory lookup is an enhancement and must never be the reason a user's
    # question goes unanswered.
    from backend.agent import memory as agent_memory
    from backend.agent.tools import registry as tool_registry
    from backend.agent.tools.registry import ToolContext

    user_id = execution.requested_by
    agent = await agent_memory.ensure_agent(session, organization_id, user_id)

    recalled: list = []
    memory_block = ""
    try:
        recalled = await agent_memory.recall(session, organization_id, user_id, query)
        memory_block = agent_memory.render_memories(recalled)
        await agent_memory.mark_recalled(session, [memory.id for memory in recalled])
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory recall failed for %s: %s", execution.id, exc)

    from backend.agent.tools import chart_tool, report_tool  # noqa: F401  (registration)

    tool_ctx = ToolContext(
        session=session,
        organization_id=organization_id,
        user_id=user_id,
        execution_id=execution.id,
        chat_session_id=execution.chat_session_id,
    )
    # The agent's allowlist is authoritative: a tool not listed is not sent to
    # the provider at all, so the model cannot call it by hallucinating a name.
    allowed = set(agent.allowed_tools or [])
    if not allowed:
        allowed = {spec.name for spec in tool_registry.all_specs()}
    active_schemas = [spec for spec in tool_registry.all_specs() if spec.name in allowed]

    # context_snapshot was created for exactly this and had never been written:
    # it records what the agent saw, so a surprising answer can be traced to the
    # memories that produced it.
    execution.context_snapshot = {
        "memories": [{"id": str(m.id), "kind": m.kind, "content": m.content} for m in recalled],
        "tools_available": [spec.name for spec in active_schemas],
        "agent_id": str(agent.id),
    }
    try:
        generated = await llm.agenerate(
            session,
            model,
            prompt=query,
            context=context,
            organization_id=organization_id,
            tool_ctx=tool_ctx if active_schemas else None,
            persona=agent.persona or "",
            extra_system=memory_block,
        )
    except ApiError as error:
        # US-313: aggregator/provider failures fail the execution cleanly.
        execution.error_code = error.code
        execution.error_message = error.message
        execution.status = "FAILED"
        execution.completed_at = _utc_now()
        await record_audit_durable(
            "execution.failed",
            organization_id=organization_id,
            actor_user_id=execution.requested_by,
            entity_type="agent_execution",
            entity_id=execution.id,
            detail={"error_code": error.code},
        )
        return _payload(execution)

    # The answer text is the model's answer, and nothing else.
    #
    # This used to prepend the retrieved passages, and separately prepend a
    # "no source found" note, to whatever the model produced. The chat pane
    # already renders provenance from the structured `citations` field, so the
    # user read the same passages twice: once as the opening block of the
    # assistant bubble, and again in the source list directly under it. On a
    # long answer the duplicated block was the majority of the message, which
    # is what the PO reported as "the AI text repeats one part at the start".
    #
    # Grounding belongs in the prompt (already sent as `context`); provenance
    # belongs in `citations` (a field the UI renders as UI). Neither belongs
    # concatenated into prose the user must scroll past. An answer with no hits
    # still reports its provenance through an empty citation list.
    text = llm.mask_pii(generated["text"])
    # US-1201/1202 metering: usage rides on the execution row.
    execution.usage = {
        "provider": generated["provider"],
        "model": generated["model"],
        "tokens_in": generated["tokens_in"],
        "tokens_out": generated["tokens_out"],
        "tool_rounds": generated.get("tool_rounds", 0),
        "tool_calls": len(generated.get("tool_calls") or []),
    }

    # Trace every tool call the model made. This is the PO's "every action must
    # be logged": the audit row says a generation happened, this says the agent
    # actually built a chart, with which arguments, and how long it took.
    for call in generated.get("tool_calls") or []:
        session.add(
            AgentToolInvocation(
                organization_id=organization_id,
                user_id=user_id,
                agent_id=agent.id,
                execution_id=execution.id,
                tool_name=call.get("name") or "",
                arguments=_truncate_json(call.get("arguments") or {}),
                ok=bool(call.get("ok")),
                error_message=None if call.get("ok") else "tool reported failure",
                result_preview=None,
                asset_id=_as_uuid((call.get("meta") or {}).get("asset_id")),
                duration_ms=int(call.get("duration_ms") or 0),
                round_index=int(call.get("round") or 0),
            )
        )
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

    # Remember the exchange for this user's agent. After the reply is persisted
    # so a memory can point at the message it came from, and wrapped because a
    # failure here must not retroactively fail a completed answer.
    try:
        await agent_memory.remember_exchange(
            session,
            organization_id=organization_id,
            user_id=user_id,
            agent=agent,
            question=query,
            answer=text,
            execution_id=execution.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory extraction failed for %s: %s", execution.id, exc)

    return _payload(execution)


def _truncate_json(value: Any, limit: int = 2000) -> Any:
    """Keep a tool trace bounded. A chart tool can be handed thousands of rows
    and the trace must not grow larger than the data it describes."""
    import json

    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_unserialisable": True}
    if len(encoded) <= limit:
        return value
    return {"_truncated": True, "_preview": encoded[:limit]}


def _as_uuid(value: Any):
    """Asset ids arrive from tool meta as strings; a malformed one must not
    abort the trace write."""
    import uuid as _uuid

    if value is None:
        return None
    try:
        return _uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


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
