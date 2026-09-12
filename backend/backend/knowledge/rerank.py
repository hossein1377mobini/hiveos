"""Reranker (PO decision 2026-09-12: quality is the priority).

Vector search is a recall stage, not a precision stage: the top-20 by cosine
distance often contains the right document at rank 7. Measured on the PO's
provider with a Persian query, cohere-rerank-v4.0-fast put the correct
document first and pushed both irrelevant documents below 0.22, which vector
distance alone did not separate (relevant 0.44 vs irrelevant 0.27).

The reranker is best-effort: if the provider is unreachable or unconfigured
the original vector order is returned unchanged, so a search never fails
because of an optional quality stage.
"""

import logging

import httpx

from backend.config import get_settings
from backend.db import session_factory
from backend.llm import read_setting

logger = logging.getLogger(__name__)

# Candidates pulled from the vector index before reranking. Wider than the
# final top_k so the reranker has something to choose from, small enough to
# stay one cheap provider call.
RERANK_CANDIDATES = 20


async def rerank(query: str, documents: list[str], top_k: int) -> list[int]:
    """Return the indices of the best documents, best first.

    Falls back to the incoming order (0..n-1) whenever reranking is not
    available, which keeps the behaviour identical to vector-only search.
    """
    fallback = list(range(len(documents)))
    settings = get_settings()
    if not settings.rerank_enabled or len(documents) < 2:
        return fallback[:top_k]

    async with session_factory() as session:
        pricing = await read_setting(session, "providers_pricing")
    base_url = (pricing.get("base_url") or settings.llm_base_url or "").rstrip("/")
    api_key = pricing.get("api_key") or settings.llm_api_key or ""
    model = pricing.get("rerank_model") or settings.rerank_model
    if not base_url or not api_key:
        return fallback[:top_k]

    try:
        async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as client:
            response = await client.post(
                f"{base_url}/rerank",
                json={
                    "model": model,
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_k, len(documents)),
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code != 200:
            logger.warning("rerank provider HTTP %s: %s", response.status_code, response.text[:300])
            return fallback[:top_k]
        results = response.json()["results"]
        order = [int(item["index"]) for item in results]
    except Exception as exc:  # noqa: BLE001 - reranking must never break search
        logger.warning("rerank failed, using vector order: %s", exc)
        return fallback[:top_k]

    # Guard against a provider returning a short or duplicated list.
    seen: set[int] = set()
    clean = [i for i in order if 0 <= i < len(documents) and not (i in seen or seen.add(i))]
    clean.extend(i for i in fallback if i not in seen)
    return clean[:top_k]

