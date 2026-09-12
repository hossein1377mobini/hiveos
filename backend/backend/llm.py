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


async def aroute_model(session: AsyncSession, requested_model: str | None) -> str:
    """Allowlist enforcement (US-1601): a model outside the admin allowlist
    falls back to the allowlist default instead of hard-failing the chat."""
    model = route_model(requested_model)
    allowlist = await read_setting(session, "models_allowlist")
    models = [m for m in (allowlist.get("models") or []) if isinstance(m, str)]
    if models:
        if model not in models:
            model = allowlist.get("default") or models[0]
    return model


async def agenerate(session: AsyncSession, model: str, prompt: str, context: str) -> dict:
    """Provider dispatch (US-1201): mock/online-mock stay deterministic and
    keyless; "openai-compatible" calls the endpoint the System Admin set in
    providers_pricing (base_url/api_key/model). Real HTTP failures surface as
    502 LLM_PROVIDER_ERROR and fail the execution cleanly."""
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
        template = await read_setting(session, "prompt_template")
        system_prompt = template.get("system") or (
            "تو دستیار هوش سازمان هستی. فقط بر اساس زمینهٔ داده‌شده پاسخ بده."
        )
        user_template = (
            template.get("user_template")
            or "{question}" + chr(10) + chr(10) + "زمینه:" + chr(10) + "{context}"
        )
        user_content = user_template.replace("{question}", prompt).replace("{context}", context)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.HTTPError as error:
            raise ApiError(502, "LLM_PROVIDER_ERROR", f"Provider unreachable: {error}") from error
        if response.status_code != 200:
            raise ApiError(
                502,
                "LLM_PROVIDER_ERROR",
                f"Provider returned HTTP {response.status_code}.",
            )
        body = response.json()
        try:
            answer = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or _estimate_tokens(prompt))
            tokens_out = int(usage.get("completion_tokens") or _estimate_tokens(answer))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ApiError(502, "LLM_PROVIDER_ERROR", "Malformed provider response.") from error
        return {
            "text": answer,
            "model": body.get("model") or model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "provider": provider,
        }

    raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", f"Provider {provider} is not configured.")


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
