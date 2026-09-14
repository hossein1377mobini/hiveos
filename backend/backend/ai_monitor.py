"""AI provider account monitoring (PO request 2026-09-13).

Answers, inside the admin panel, the two questions the PO actually has:
"how much AI credit is left" and "what is it being spent on". AvalAI exposes a
dedicated account API at /user/v1 - separate from the inference API at /v1 -
documented at https://docs.avalai.ir/fa/api-reference/user

Two things this module must never do: break the panel, and leak the key. Any
plain OpenAI-compatible endpoint implements no /user/v1 at all, so that case
reports state "unsupported" instead of raising; the api_key is never echoed.
"""

import time

import httpx

from backend.llm import read_setting

# The account API is cheap but polled by the panel; a minute of staleness is
# invisible to the PO and keeps us far below the tier rate limit.
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL_SECONDS = 60.0


def user_api_base(base_url: str | None) -> str | None:
    """AvalAI's account API sits beside the inference API: /v1 -> /user/v1.

    Returns None for any other provider, which is how a generic endpoint is
    recognised as having no account API rather than being told it is broken.
    """
    if not base_url:
        return None
    trimmed = base_url.strip().rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[: -len("/v1")] + "/user/v1"
    return None


def _mask(key: str | None) -> str | None:
    if not key or len(key) < 8:
        return None
    return "..." + key[-4:]


def _money(value: object) -> float | None:
    """Amounts arrive as strings in some fields and numbers in others."""
    try:
        return round(float(value), 2)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def _get(
    client: httpx.AsyncClient, base: str, path: str, key: str, params: dict | None = None
) -> tuple[dict | None, str | None]:
    try:
        response = await client.get(
            f"{base}{path}", headers={"Authorization": f"Bearer {key}"}, params=params
        )
    except httpx.HTTPError as error:
        return None, f"unreachable: {error}"
    if response.status_code != 200:
        # The provider body is not surfaced: it can echo the key back.
        return None, f"HTTP {response.status_code}"
    try:
        return response.json(), None
    except ValueError:
        return None, "malformed response"


def _packages(credit: dict) -> list[dict]:
    """Per-package credit, including which models each one still covers.

    AvalAI scopes most credit to a model allowlist, so "can I call this model"
    is a property of the package, not of the account total: gpt-5-mini fails
    with insufficient_quota while deepseek-v4.1-flash on the same account
    answers fine. The PO needs that list to pick a working model.
    """
    sources = credit.get("credit_sources") or {}
    now = time.time()
    out: list[dict] = []
    for item in sources.get("packages") or []:
        if not isinstance(item, dict):
            continue
        remaining = _money(item.get("remaining_irt"))
        models: list[str] = []
        for names in (item.get("scope_details") or {}).values():
            if isinstance(names, list):
                models.extend(str(n) for n in names)
        expiry = item.get("end_date")
        days_left: float | None = None
        if isinstance(expiry, str):
            try:
                from datetime import datetime

                parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                days_left = round((parsed.timestamp() - now) / 86400, 2)
            except ValueError:
                days_left = None
        out.append(
            {
                "name": item.get("name"),
                "description": item.get("description"),
                "remaining_irt": remaining,
                "amount_irt": _money(item.get("amount_irt")),
                "end_date": expiry,
                "days_left": days_left,
                "models": sorted(set(models)),
            }
        )
    return out


def _usage_totals(payload: dict) -> dict:
    totals = payload.get("totals") or {}
    tokens = totals.get("tokens") or {}
    cost = totals.get("cost") or {}
    period = payload.get("period") or {}
    return {
        # The provider returns the window as explicit timestamps, not a count.
        "period_start": period.get("start"),
        "period_end": period.get("end"),
        "transactions": totals.get("transactions"),
        "tokens_total": tokens.get("total"),
        "tokens_prompt": tokens.get("prompt"),
        "tokens_completion": tokens.get("completion"),
        "tokens_cached": tokens.get("cached"),
        "cost_unit": _money(cost.get("unit")),
        "cost_irt": _money(cost.get("paid_irt")),
    }


def _usage_by_model(payload: dict) -> list[dict]:
    rows = []
    for row in payload.get("by_model") or []:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "model": row.get("model"),
                "transactions": row.get("transactions"),
                "tokens": row.get("tokens"),
                "cost_unit": _money(row.get("cost_unit")),
            }
        )
    rows.sort(key=lambda r: r.get("cost_unit") or 0, reverse=True)
    return rows


async def read_account(session, hours: int = 24) -> dict:
    """Credit + recent usage for the configured provider, cached for a minute."""
    cached = _CACHE.get("account")
    now = time.time()
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]

    config = await read_setting(session, "providers_pricing")
    base_url = config.get("base_url")
    api_key = config.get("api_key")
    provider = config.get("provider")

    result: dict = {
        "provider": provider,
        "base_url": base_url,
        "api_key_masked": _mask(api_key),
        "configured_models": {
            "chat": config.get("chunk_model"),
            "embedding": config.get("embedding_model"),
            "rerank": config.get("rerank_model"),
        },
    }

    account_base = user_api_base(base_url)
    # Embeddings and reranking run on this server (ADR-024), so there is no
    # account API to read when the provider is not configured for chat.
    if provider != "openai-compatible" or not account_base or not api_key:
        result.update(
            {
                "state": "unsupported",
                "reason": "NO_ACCOUNT_API",
                "credit": None,
                "usage": None,
                "packages": [],
            }
        )
        _CACHE["account"] = (now, result)
        return result

    async with httpx.AsyncClient(timeout=20.0) as client:
        credit, credit_error = await _get(client, account_base, "/credit", api_key)
        usage, usage_error = await _get(
            client,
            account_base,
            "/transactions/summary",
            api_key,
            {"hours_ago": hours, "group_by": "model"},
        )

    if credit is None and usage is None:
        result.update(
            {
                "state": "error",
                "reason": "ACCOUNT_API_FAILED",
                "detail": credit_error or usage_error,
                "credit": None,
                "usage": None,
                "packages": [],
            }
        )
        _CACHE["account"] = (now, result)
        return result

    packages = _packages(credit or {})
    result.update(
        {
            "state": "ok",
            "reason": None,
            "credit": {
                "remaining_irt": _money((credit or {}).get("remaining_irt")),
                "remaining_unit": (credit or {}).get("remaining_unit"),
                "total_unit": (credit or {}).get("total_unit"),
                "exchange_rate": (credit or {}).get("exchange_rate"),
                "account_tier": (credit or {}).get("account_tier"),
            }
            if credit
            else None,
            "usage": _usage_totals(usage or {}) if usage else None,
            "usage_by_model": _usage_by_model(usage or {}) if usage else [],
            "packages": packages,
            # Union of every model still covered by a live package - the PO can
            # read this to know which model will actually answer.
            "covered_models": sorted({m for p in packages for m in p["models"]}),
            "usage_error": usage_error,
        }
    )
    _CACHE["account"] = (now, result)
    return result


def clear_cache() -> None:
    _CACHE.clear()
