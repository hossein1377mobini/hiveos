"""LLM aggregator client + model router (US-1201/1202, T-S3-6).

ADR-020/023: direct mode — HiveOS talks to the model provider through
this single seam; the gateway complexity stays out of the runtime. In
v0.1 the provider is "mock": deterministic, no external calls, no keys
(ADR-022). The real online provider (US-1201) plugs into generate() for
staging/prod without touching the runtime.
"""

import hashlib
import math

from backend.api_errors import ApiError
from backend.config import get_settings

PROVIDERS = ("mock",)


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
    """Deterministic mock generation with token metering (US-1201 AC)."""
    settings = get_settings()
    if settings.llm_provider != "mock":
        raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", f"Provider {settings.llm_provider} is not configured.")
    digest = hashlib.sha256(f"{model}:{prompt}:{context}".encode()).hexdigest()[:12]
    answer = f"[mock:{model}#{digest}] پاسخ تولیدشده بر اساس زمینه ارائه‌شده."
    return {
        "text": answer,
        "model": model,
        "tokens_in": _estimate_tokens(f"{prompt}\n{context}"),
        "tokens_out": _estimate_tokens(answer),
    }
