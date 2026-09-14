"""LLM aggregator client + model router (US-1201/1202, T-S3-6).

ADR-020/023: direct mode — HiveOS talks to the model provider through
this single seam; the gateway complexity stays out of the runtime. In
v0.1 the provider is "mock": deterministic, no external calls, no keys
(ADR-022). The real online provider (US-1201) plugs into generate() for
staging/prod without touching the runtime.
"""

import hashlib
import math
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.config import get_settings
from backend.models import SystemSetting

PROVIDERS = ("mock", "openai-compatible")

# RG-18 minimal guardrails (epic-11 base, PO 2026-09-02 decision):
_MOBILE_RE = re.compile(r"09\d{9}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NID_RE = re.compile(r"\b\d{10}\b")
_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        "ignore (all |any )?(previous|prior) instructions",
        "system prompt:",
        "you are now",
    )
]


def mask_pii(text: str) -> str:
    """US-1102: basic PII masking on model output."""
    masked = _MOBILE_RE.sub("۰۹•••••••••", text)
    masked = _EMAIL_RE.sub("[email-masked]", masked)
    return _NID_RE.sub("[digits-masked]", masked)


def sanitize_prompt(text: str) -> str:
    """US-1103: basic prompt-injection mitigation on user input."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return "[input-neutralized]"
    return text


def route_model(requested_model: str | None) -> str:
    """US-1202 (direct mode): normalize the requested model name."""
    settings = get_settings()
    model = (requested_model or settings.llm_default_model).strip()
    if len(model) > 100 or "/" in model and len(model.split("/")) > 2:
        raise ApiError(400, "VALIDATION_ERROR", "Unknown model name.")
    return model


# ---------------------------------------------------------------------------
# Admin-panel driven runtime (epic-16 zero-open): the System Admin sets
# provider credentials, the model allowlist, pricing and the prompt template
# through /api/v1/admin/settings/* — the runtime reads them per call.
# ---------------------------------------------------------------------------

async def read_setting(session: AsyncSession, key: str) -> dict:
    row = (
        await session.execute(select(SystemSetting).where(SystemSetting.key == key))
    ).scalar_one_or_none()
    return (row.value or {}) if row else {}


def provider_error(status_code: int, raw: str) -> tuple[int, str, str]:
    """Translate a provider failure into something the PO can act on.

    HTTP 429 alone is not actionable: the same status covers an exhausted
    account balance and a genuine rate limit, and the PO needs to know whether
    to top up the account or slow down. The provider body is never forwarded;
    only the reason we recognise becomes a code.
    """
    lowered = (raw or "").lower()
    if status_code in (401, 403):
        return 502, "LLM_PROVIDER_AUTH", f"Provider rejected the key (HTTP {status_code})."
    if status_code == 402 or "insufficient" in lowered or "quota" in lowered or "balance" in lowered:
        return 502, "LLM_PROVIDER_CREDIT", "The provider account is out of credit."
    if status_code == 429:
        return 502, "LLM_PROVIDER_RATE_LIMIT", "The provider is rate limiting this server."
    if status_code in (400, 404):
        return 502, "LLM_PROVIDER_MODEL", f"Provider rejected the request (HTTP {status_code})."
    return 502, "LLM_PROVIDER_ERROR", f"Provider returned HTTP {status_code}."


async def aroute_model(session: AsyncSession, requested_model: str | None) -> str:
    """Pick the model that writes the answer.

    Order of precedence: an explicit request, the panel's answer_model, the
    allowlist, then the environment default. The panel wins over the env
    default because the System Admin is the only one who knows which model the
    account is actually funded for.
    """
    pricing = await read_setting(session, "providers_pricing")
    answer_model = (pricing.get("answer_model") or "").strip()
    # A chat session with no settings carries the placeholder "hive-mind-default"
    # (see chat/service.py DEFAULT_SETTINGS). Sending that string to the provider
    # is meaningless, so treat it as "no preference".
    requested = (requested_model or "").strip()
    if requested == "hive-mind-default":
        requested = ""
    model = route_model(requested or answer_model or None)
    allowlist = await read_setting(session, "models_allowlist")
    models = [m for m in (allowlist.get("models") or []) if isinstance(m, str)]
    if models and model not in models:
        model = allowlist.get("default") or models[0]
    return model


async def _system_prompt(session: AsyncSession, organization_id=None) -> str:
    """The system prompt for this call: the panel's value, else the code default.

    The fallback here used to be a single sentence ("تو دستیار هوش سازمان هستی.
    فقط بر اساس زمینهٔ داده‌شده پاسخ بده.") while the full multi-section prompt in
    brain/prompt_template.py was only ever used at brain-initialization time and
    stored on the brain row. So the answer style the PO edits in the admin panel
    reached every provider, but the default a fresh deployment actually answered
    with was one line, and none of the grounding/format/language rules applied.
    Both paths now agree: an unset setting means the same text the brain stores.

    The {business_description} placeholder is filled here rather than left to the
    admin's 'system' field, because the panel shows that field without a
    placeholder substitution step and a literal '{business_description}' would be
    sent to the model verbatim.
    """
    from backend.brain.prompt_template import DEFAULT_SYSTEM_PROMPT_TEMPLATE

    template = await read_setting(session, "prompt_template")
    stored = (template.get("system") or "").strip()
    text = stored or DEFAULT_SYSTEM_PROMPT_TEMPLATE
    if "{business_description}" not in text:
        return text

    description = ""
    if organization_id is not None:
        from backend.models import Organization

        org = await session.get(Organization, organization_id)
        description = (org.business_description or "") if org is not None else ""
    return text.format(
        business_description=description or "توصیف کسب‌وکار برای این سازمان ثبت نشده است."
    )


async def agenerate(
    session: AsyncSession,
    model: str,
    prompt: str,
    context: str,
    organization_id=None,
    *,
    tool_ctx=None,
    persona: str = "",
    extra_system: str = "",
) -> dict:
    """Provider dispatch (US-1201): mock/online-mock stay deterministic and
    keyless; "openai-compatible" calls the endpoint the System Admin set in
    providers_pricing (base_url/api_key/model). Real HTTP failures surface as
    502 LLM_PROVIDER_ERROR and fail the execution cleanly.

    Per-user agent additions (PO 2026-09):

    - `tool_ctx` is a backend.agent.tools.registry.ToolContext. When present,
      the tool schemas go out with the request and the model's tool_calls are
      executed in a bounded loop. When absent the call is exactly what it was
      before, so every existing caller is unaffected.
    - `persona` and `extra_system` append to the system prompt: the user's
      agent persona, and the retrieved memories. They are appended rather than
      substituted so the org-level grounding rules can never be displaced by a
      per-user string.
    """
    pricing = await read_setting(session, "providers_pricing")
    provider = pricing.get("provider") or get_settings().llm_provider

    if provider in ("mock", "online-mock"):
        result = generate(model, prompt=prompt, context=context)
        result["provider"] = provider
        return result

    if provider == "openai-compatible":
        # Panel-first, env as the bootstrap fallback (PO 2026-09-12).
        base_url = (pricing.get("base_url") or get_settings().llm_base_url or "").rstrip("/")
        api_key = pricing.get("api_key") or get_settings().llm_api_key or ""
        if not base_url or not api_key:
            raise ApiError(
                503,
                "PROVIDER_NOT_CONFIGURED",
                "Provider credentials are missing — set them in the admin panel.",
            )
        from backend.brain.prompt_template import DEFAULT_USER_TEMPLATE

        template = await read_setting(session, "prompt_template")
        system_prompt = await _system_prompt(session, organization_id)
        user_template = template.get("user_template") or DEFAULT_USER_TEMPLATE
        user_content = user_template.replace("{question}", prompt).replace("{context}", context)
        messages: list[dict] = [{"role": "system", "content": _compose_system(system_prompt, persona, extra_system)}]
        messages.append({"role": "user", "content": user_content})
        headers = {"Authorization": f"Bearer {api_key}"}

        tool_schemas = None
        if tool_ctx is not None:
            from backend.agent.tools import registry

            tool_schemas = registry.provider_schemas()
            if not tool_schemas:
                tool_schemas = None

        tokens_in = 0
        tokens_out = 0
        tool_calls_made: list[dict] = []
        rounds = 0

        while True:
            payload: dict = {"model": model, "messages": messages}
            if tool_schemas:
                payload["tools"] = tool_schemas
                payload["tool_choice"] = "auto"
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{base_url}/chat/completions", json=payload, headers=headers
                    )
            except httpx.HTTPError as error:
                raise ApiError(502, "LLM_PROVIDER_ERROR", f"Provider unreachable: {error}") from error
            if response.status_code != 200:
                # PO 2026-09-12: an out-of-credit account must not look like a
                # transient outage - the PO has to know to top the account up.
                status_code, code, message = provider_error(response.status_code, response.text)
                raise ApiError(status_code, code, message)
            body = response.json()
            try:
                message = body["choices"][0]["message"]
                usage = body.get("usage") or {}
                tokens_in += int(usage.get("prompt_tokens") or _estimate_tokens(prompt))
                tokens_out += int(usage.get("completion_tokens") or 0)
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise ApiError(502, "LLM_PROVIDER_ERROR", "Malformed provider response.") from error

            calls = message.get("tool_calls") or []
            if not calls:
                answer = message.get("content") or ""
                if not tokens_out:
                    tokens_out = _estimate_tokens(answer)
                return {
                    "text": answer,
                    "model": body.get("model") or model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "provider": provider,
                    "tool_calls": tool_calls_made,
                    "tool_rounds": rounds,
                }

            # The model asked for tools. Echo its own turn back verbatim - an
            # assistant message carrying tool_calls must precede the tool
            # messages or the provider rejects the conversation as malformed.
            messages.append(message)
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name") or ""
                raw_args = function.get("arguments") or "{}"
                arguments = _parse_tool_arguments(raw_args)
                result, elapsed_ms = await registry.invoke(tool_ctx, name, arguments)
                tool_calls_made.append(
                    {
                        "name": name,
                        "arguments": arguments,
                        "ok": result.ok,
                        "duration_ms": elapsed_ms,
                        "round": rounds,
                        "meta": result.meta,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": result.content,
                    }
                )

            rounds += 1
            if rounds >= registry.MAX_TOOL_ROUNDS:
                # Tell the model to answer with what it has rather than looping
                # until the provider times out. This is a normal user turn, not
                # an error, so the execution still completes.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "به سقف تعداد فراخوانی ابزار رسیدی. حالا بر اساس "
                            "همان اطلاعاتی که تا اینجا به دست آوردی پاسخ نهایی را بده."
                        ),
                    }
                )
                tool_schemas = None

    raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", f"Provider {provider} is not configured.")


def _compose_system(base: str, persona: str, extra_system: str) -> str:
    """base (org grounding) + user persona + retrieved memory.

    Order matters: grounding first, then the per-user layer, then the recalled
    context. A persona that argues with the citation rules loses, because the
    rules are stated first and the persona is framed as a refinement.
    """
    parts = [base]
    if persona.strip():
        parts.append("لحن و ترجیحات این کاربر:\n" + persona.strip())
    if extra_system.strip():
        parts.append(extra_system.strip())
    return "\n\n".join(parts)


def _parse_tool_arguments(raw: str) -> dict:
    """Tool arguments arrive as a JSON *string*, and a small model will
    occasionally emit malformed JSON. Returning {} lets the tool report its own
    missing-argument error to the model instead of aborting the execution."""
    import json

    if isinstance(raw, dict):  # some aggregators pre-parse it
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def generate(model: str, prompt: str, context: str) -> dict:
    """Deterministic generation with token metering (US-1201 AC).

    Providers: "mock" (keyless dev/CI) and "online-mock" (same output but
    billed through the wallet gate — tests/staging dry-run). Any other
    configured provider needs a real client call.
    """
    settings = get_settings()
    if settings.llm_provider not in ("mock", "online-mock"):
        raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", f"Provider {settings.llm_provider} is not configured.")
    digest = hashlib.sha256(f"{model}:{prompt}:{context}".encode()).hexdigest()[:12]
    answer = f"[mock:{model}#{digest}] پاسخ تولیدشده بر اساس زمینه ارائه‌شده."
    return {
        "text": answer,
        "model": model,
        "tokens_in": _estimate_tokens(f"{prompt}\n{context}"),
        "tokens_out": _estimate_tokens(answer),
    }