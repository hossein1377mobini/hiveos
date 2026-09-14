"""Tool registry for the per-user agent (Phase 0 of the per-user agent plan).

Why an in-process registry instead of MCP:

The catalogs name FastMCP as the tool-delivery mechanism, and it is the right
answer for *remote* tools. It is the wrong answer for the tools we actually
have. Every HiveOS tool runs in this same Python process and touches the same
AsyncSession: the chart builder reads the org's own query results, the report
builder writes a KnowledgeAsset row through reporting.save_report. An MCP hop
would serialise the args to JSON, cross a transport, and hand the callee a
fresh session with no tenant context - we would then have to re-authenticate
the caller and re-establish organization_id over the wire, to reach code that
is already in scope.

So the registry is a plain dict of name -> ToolSpec, and the loop in llm.py
calls the functions directly. If a genuinely out-of-process tool appears later
(it does not exist in either catalog today), it registers here as a thin
adapter that speaks MCP behind the same ToolSpec interface. The agent's view
does not change.

Every tool contract, learned from the production system prompts surveyed for
the prompt rewrite:

- The description is what the model routes on, so it is written for the model,
  not for a human reading the source. It says WHEN to call the tool, what the
  arguments mean, and what it returns.
- `parameters` is a JSON Schema object, the exact shape the OpenAI-compatible
  /chat/completions expects under `tools[].function.parameters`.
- A tool never raises to the model. A failure is returned as a result with
  `ok: False` and a Persian reason, because an exception would abort the whole
  execution and the model never gets to recover or explain.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# Six rounds is a ceiling, not a target. A model that has not converged after
# six tool calls is looping, and every extra round is a paid provider call plus
# a wall-clock second the user spends staring at a spinner. Hitting the cap is
# reported to the model as a normal tool result so it can answer with what it
# has instead of the execution failing.
MAX_TOOL_ROUNDS = 6


@dataclass
class ToolResult:
    """What a tool hands back to the loop.

    `content` is the string the model actually reads, so it must be compact and
    self-describing - a JSON blob of hundreds of rows burns the context window
    that the answer needs. `ok` is separate from `content` so the loop can log
    a failure without pattern-matching on prose.
    """

    content: str
    ok: bool = True
    # Structured side-channel for the audit row and the tool-invocation table.
    # Never sent to the model: it is for us to trace, not for the model to read.
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    """Everything a tool is allowed to know about the call.

    organization_id and user_id are both present and both mandatory. This is
    the per-user agent's isolation contract (ADR-024 extended): a tool may read
    org-scoped data, but a memory or a generated asset is attributed to the
    *user* whose agent invoked it, so two colleagues at the same company never
    see each other's memories.
    """

    session: AsyncSession
    organization_id: uuid.UUID
    user_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    chat_session_id: uuid.UUID | None = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    # Deny-by-default is unnecessary here (all tools are first-party) but the
    # flag exists because a future write-capable tool must be opt-in per agent.
    writes: bool = False

    def to_provider_schema(self) -> dict[str, Any]:
        """The exact shape /chat/completions expects under tools[]."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    if spec.name in _REGISTRY:  # a duplicate name would shadow silently
        raise RuntimeError(f"tool {spec.name!r} is already registered")
    _REGISTRY[spec.name] = spec


def get(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def all_specs() -> list[ToolSpec]:
    """Stable order so the provider payload is byte-identical between turns.

    A reordered tools[] array invalidates the provider's prompt cache and, on
    some aggregators, counts as a new request shape.
    """
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def provider_schemas() -> list[dict[str, Any]]:
    return [spec.to_provider_schema() for spec in all_specs()]


def clear() -> None:
    """Test hook: tool modules register at import, so a re-import must not trip
    the duplicate guard."""
    _REGISTRY.clear()


async def invoke(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> tuple[ToolResult, int]:
    """Run one tool call, converting any failure into a model-readable result.

    Returns (result, elapsed_ms). Never raises: a tool bug becomes a tool result
    with ok=False so the model can tell the user what it could not do, instead
    of the execution dying with an opaque 500.
    """
    spec = get(name)
    if spec is None:
        return ToolResult(content=f"ابزار «{name}» وجود ندارد.", ok=False), 0
    started = time.monotonic()
    try:
        result = await spec.handler(ctx, arguments)
    except Exception as exc:  # noqa: BLE001 - a tool failure must not kill the run
        elapsed = int((time.monotonic() - started) * 1000)
        return (
            ToolResult(content=f"اجرای ابزار «{name}» ناموفق بود: {exc}", ok=False),
            elapsed,
        )
    return result, int((time.monotonic() - started) * 1000)
