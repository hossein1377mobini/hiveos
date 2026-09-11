"""Embedding providers (US-212, T-S2-6).

- 'local': BAAI/bge-m3 through sentence-transformers, lazily loaded once
  per process (ADR-023 single worker). Requires the model weights on the
  host (staging/prod) - on failure raises EMBEDDING_UNAVAILABLE.
- 'mock': deterministic sha256-based vectors (dev/CI/offline) - same text
  always yields the same vector, so acceptance tests can assert ranking.
The provider is config-driven (EMBEDDING_PROVIDER=local|mock).
"""

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

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of normalized texts; returns unit vectors."""
    settings = get_settings()
    dim = settings.embedding_dim
    if settings.embedding_provider == "mock":
        return [_mock_vector(text, dim) for text in texts]
    try:
        model = _load_local()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - model/runtime failures -> clear API error
        # H1 (external review): never leak host/model internals to clients;
        # the details stay in the server log only.
        logger.error("embedding model failure: %s", exc)
        raise ApiError(503, "EMBEDDING_UNAVAILABLE", "The embedding model is unavailable.") from exc


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]
