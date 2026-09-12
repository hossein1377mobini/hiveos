"""Embedding providers (US-212, T-S2-6 + PO decision 2026-09-12).

- 'remote': the online provider configured in the admin panel
  (providers_pricing.base_url / api_key). PO decision: quality matters more
  than running the model locally, and 1536-dim remote vectors beat a
  quantised local model on Persian. No torch, no weights on the host.
- 'local': BAAI/bge-m3 through sentence-transformers, lazily loaded once
  per process. Kept for on-prem deployments that cannot reach the internet.
- 'mock': deterministic sha256-based vectors (dev/CI/offline) - same text
  always yields the same vector, so acceptance tests can assert ranking.

Dimensions differ per provider (remote 1536, local 1024), so the knowledge
base records which model produced each vector and never mixes them.
"""

import asyncio
import hashlib
import logging
import math

from backend.api_errors import ApiError
from backend.config import get_settings

_model = None  # process-wide singleton


def _load_local():
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ApiError(
            503, "EMBEDDING_UNAVAILABLE", "sentence-transformers is not installed."
        ) from exc
    settings = get_settings()
    _model = SentenceTransformer(settings.embedding_model)
    return _model


def _mock_vector(text: str, dim: int) -> list[float]:
    values: list[float] = []
    for index in range(dim):
        digest = hashlib.sha256(f"{index}:{text}".encode()).digest()
        byte = digest[0]
        values.append((byte / 255.0) * 2.0 - 1.0)  # [-1, 1]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


logger = logging.getLogger(__name__)

async def _remote_vectors(texts: list[str]) -> list[list[float]]:
    """Embed through the provider the System Admin configured in the panel.

    PO decision 2026-09-12: quality first. A hosted multilingual model beats a
    quantised local one on Persian for embedding, and it removes torch/weights
    from the server entirely.
    """
    import httpx

    settings = get_settings()
    # Panel-first (US-1601 zero-open): the System Admin edits base_url/api_key
    # under "درگاه مدل و قیمت" and the runtime picks them up per call. The env
    # values are only a fallback for a fresh install before the first save.
    from backend.db import session_factory
    from backend.llm import read_setting

    async with session_factory() as session:
        pricing = await read_setting(session, "providers_pricing")
    base_url = (pricing.get("base_url") or settings.llm_base_url or "").rstrip("/")
    api_key = pricing.get("api_key") or settings.llm_api_key or ""
    model = pricing.get("embedding_model") or settings.embedding_remote_model
    # Width is a per-provider knob (OpenAI-style models accept "dimensions");
    # it must match the pgvector column, which is validated at migration time.
    dimensions = int(pricing.get("embedding_dimensions") or settings.embedding_remote_dim)
    if not base_url or not api_key:
        raise ApiError(
            503,
            "PROVIDER_NOT_CONFIGURED",
            "Embedding credentials are missing - set them in the admin panel.",
        )
    try:
        async with httpx.AsyncClient(timeout=settings.embedding_timeout_seconds) as client:
            response = await client.post(
                f"{base_url}/embeddings",
                json={"model": model, "input": texts, "dimensions": dimensions},
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        logger.error("embedding provider unreachable: %s", exc)
        raise ApiError(
            503, "EMBEDDING_UNAVAILABLE", "The embedding service is unreachable."
        ) from exc
    if response.status_code != 200:
        # F: the bare status hid whether it was the key, the quota or the model
        # name - log the provider body, keep the client message generic.
        logger.error("embedding provider HTTP %s: %s", response.status_code, response.text[:500])
        raise ApiError(503, "EMBEDDING_UNAVAILABLE", "The embedding service refused the request.")
    try:
        payload = response.json()
        # The API may return rows out of order; index is authoritative.
        rows = sorted(payload["data"], key=lambda row: row.get("index", 0))
        return [[float(value) for value in row["embedding"]] for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("embedding provider returned an unexpected payload: %s", payload)
        raise ApiError(
            503, "EMBEDDING_UNAVAILABLE", "The embedding service returned an unexpected response."
        ) from exc


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of normalized texts; returns unit vectors."""
    settings = get_settings()
    if settings.embedding_provider == "mock":
        return [_mock_vector(text, settings.embedding_dim) for text in texts]
    try:
        if settings.embedding_provider == "remote":
            return await _remote_vectors(texts)
        # The local model is CPU-bound; keep it off the event loop.
        return await asyncio.to_thread(_local_vectors, texts)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - model/runtime failures -> clear API error
        # H1 (external review): never leak host/model internals to clients;
        # the details stay in the server log only.
        logger.error("embedding model failure: %s", exc)
        raise ApiError(503, "EMBEDDING_UNAVAILABLE", "The embedding model is unavailable.") from exc


def _local_vectors(texts: list[str]) -> list[list[float]]:
    """CPU-bound local encode; runs in a worker thread, never on the loop."""
    try:
        model = _load_local()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - model/runtime failures -> clear API error
        # H1 (external review): never leak host/model internals to clients;
        # the details stay in the server log only.
        logger.error("local embedding model failure: %s", exc)
        raise ApiError(503, "EMBEDDING_UNAVAILABLE", "The embedding model is unavailable.") from exc


async def embed_one(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
