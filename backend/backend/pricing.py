"""AvalAI per-token pricing (PO requirement 2026-09).

"میزان مصرف هر کاربر باید دقیقا برمبنای نحوه محاسبه میزان مصرف توی مستندات
aval ai باشه. هر طور که اون انجام میده ما هم باید."

The per-user charge must be computed exactly the way AvalAI computes it, so the
USD figure this module produces is the provider's own arithmetic applied to the
provider's own published prices - not a local approximation of it.

WHERE THE PRICES COME FROM
--------------------------
`GET https://api.avalai.ir/public/models` is AvalAI's authoritative price list
and it is PUBLIC: no API key, one entry per model, `pricing` in USD per
1,000,000 tokens. Verified against the live endpoint (359 models at the time of
writing). Fields are read defensively: the list keeps gaining keys
(`image_input`, `search_context_cost_per_query`, ...) and a model may carry no
usable pricing block at all. The doc's own instruction, from
/fa/guides/token-counting, is to reconcile the real cost against the response
`usage` object - which is what execution/service.py stores on the execution.

THE THREE CLASSES AVALAI BILLS
------------------------------
    input, cached_input (much cheaper), output

which an OpenAI-compatible `usage` object reports as `prompt_tokens`,
`prompt_tokens_details.cached_tokens` (Anthropic-style responses use
`cache_read_input_tokens`) and `completion_tokens`. Reasoning tokens are a
SUBSET of `completion_tokens` in that wire format, so they are recorded on the
execution but never added to the cost a second time. Anthropic-style
`cache_creation_input_tokens` are likewise already inside `prompt_tokens` and
are billed at the plain input rate, which is what the formula below does.

Image models price `image_input` / `image_cached_input` / `image_output`.
That is irrelevant today: this runtime answers text-only chat requests
(`/chat/completions` with `messages`), so no image token ever appears in a
usage object here. If the agent ever starts sending images or calling
`/images/*`, this module needs an image-token branch instead of silently
pricing those tokens at the text rate.
"""

import math
import time
from urllib.parse import urlparse

import httpx

CATALOG_URL = "https://api.avalai.ir/public/models"

# AvalAI prices per 1,000,000 tokens; every rate below is USD per token.
TOKENS_PER_PRICE_UNIT = 1_000_000

# One hour of staleness is invisible next to the per-execution cost it
# describes, and it keeps the panel and every answer far below the tier rate
# limit. House style follows ai_monitor._CACHE/_TTL_SECONDS: a module-level
# cache, an explicit refresh, and a clear_cache() for tests.
_TTL_SECONDS = 3600.0
_CACHE: dict[str, tuple[float, dict]] = {}


def _number(value: object) -> float | None:
    """Rates arrive as numbers or numeric strings; anything else is absent."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _count(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def is_avalai(base_url: str | None) -> bool:
    """Whether AvalAI's published prices describe this endpoint at all.

    A price list is only meaningful for the provider that publishes it: an
    operator pointing base_url at some other OpenAI-compatible service is not
    served by AvalAI's rates, so billing degrades to the admin fallback rate
    instead of charging AvalAI's numbers for somebody else's tokens.
    """
    if not base_url:
        return False
    host = (urlparse(str(base_url).strip()).hostname or "").lower()
    return host == "avalai.ir" or host.endswith(".avalai.ir")


async def fetch_catalog(*, refresh: bool = False) -> dict[str, dict] | None:
    """model id -> pricing block, cached for _TTL_SECONDS.

    Returns None when the catalog has never been fetched successfully, which is
    how a caller knows to fall back rather than to bill zero. A failed refresh
    keeps serving the last good catalog: a stale price is far better than
    dropping every user onto the fallback rate because one request timed out.
    """
    now = time.time()
    cached = _CACHE.get("catalog")
    if not refresh and cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]
    stale = cached[1] if cached else None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(CATALOG_URL)
    except httpx.HTTPError:
        return stale
    if response.status_code != 200:
        return stale
    try:
        body = response.json()
    except ValueError:
        return stale
    entries = body.get("data") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        return stale
    catalog: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        pricing = entry.get("pricing")
        catalog[model_id] = pricing if isinstance(pricing, dict) else {}
    _CACHE["catalog"] = (now, catalog)
    return catalog


def clear_cache() -> None:
    _CACHE.clear()


def catalog_pricing(catalog: dict[str, dict] | None, model: str | None) -> dict | None:
    """This model's pricing block, or None when the catalogue has no entry.

    An entry with an EMPTY block comes back as an empty dict, not as None:
    "this model published no usable price" and "this catalogue does not list
    this model" are different facts and must not collapse into one.
    """
    if not catalog or not model:
        return None
    if str(model) not in catalog:
        return None
    pricing = catalog[str(model)]
    return pricing if isinstance(pricing, dict) else None


def usd_cost(
    pricing: dict | None,
    *,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
) -> float | None:
    """AvalAI's cost for one call, in USD.

        usd = ((prompt_tokens - cached_tokens) * pricing.input
               + cached_tokens * pricing.cached_input
               + completion_tokens * pricing.output) / 1_000_000

    None means "I cannot price this", never "this was free": a model with no
    pricing block, or with both text rates missing/zero, must fall back to the
    admin rate rather than silently bill zero.
    """
    if not pricing:
        return None
    input_rate = _number(pricing.get("input"))
    output_rate = _number(pricing.get("output"))
    if input_rate is None or output_rate is None:
        return None
    if input_rate <= 0 and output_rate <= 0:
        return None
    cached_rate = _number(pricing.get("cached_input"))
    if cached_rate is None:
        # No cached price published: AvalAI bills those tokens as fresh input
        # rather than for free, so never invent a discount.
        cached_rate = input_rate

    prompt = _count(prompt_tokens)
    # A provider that reports more cached tokens than prompt tokens is
    # self-contradictory; clamp so the fresh-input term cannot go negative.
    cached = min(_count(cached_tokens), prompt)
    completion = _count(completion_tokens)
    total = (prompt - cached) * input_rate + cached * cached_rate + completion * output_rate
    return total / TOKENS_PER_PRICE_UNIT


def price_usage(catalog: dict[str, dict] | None, model: str | None, usage: dict) -> dict:
    """The full cost basis for one execution: what it cost and on what basis.

    `usage` uses this runtime's own names (tokens_in / tokens_out /
    cached_tokens / reasoning_tokens) so the caller does not need to know which
    wire shape the provider used.
    """
    prompt_tokens = _count(usage.get("tokens_in"))
    completion_tokens = _count(usage.get("tokens_out"))
    cached_tokens = _count(usage.get("cached_tokens"))
    pricing = catalog_pricing(catalog, model)
    usd = usd_cost(
        pricing,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        completion_tokens=completion_tokens,
    )
    if catalog is None:
        source = "catalog_unavailable"
    elif pricing is None:
        source = "model_not_in_catalog"
    elif usd is None:
        source = "pricing_missing"
    else:
        source = "avalai_public_models"
    return {
        "catalog_url": CATALOG_URL,
        "source": source,
        "known": usd is not None,
        "usd": usd,
        "model": model,
        "tokens_in": prompt_tokens,
        "tokens_out": completion_tokens,
        "cached_tokens": cached_tokens,
        "reasoning_tokens": _count(usage.get("reasoning_tokens")),
        "pricing": pricing,
    }


def ceil_credits(usd: float, credits_per_usd: float) -> int:
    """USD -> internal credit, rounded up so a paid token is never lost.

    The wallet is an integer ledger (wallets.balance is an Integer with a
    non-negative check), so the conversion has to land on a whole credit; the
    ceiling is the same direction the pre-existing fallback rate already
    rounded.
    """
    return max(1, int(math.ceil(float(usd) * float(credits_per_usd))))
