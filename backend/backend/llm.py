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

from backend.api_errors import ApiError
from backend.config import get_settings

PROVIDERS = ("mock",)

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
