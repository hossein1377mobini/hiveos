"""Local ONNX inference for embeddings and reranking (PO decision 2026-09-12).

Why ONNX instead of sentence-transformers: the host has no GPU, and torch
costs ~19GB of image and ~2.5GB of RAM per model to do the same matmuls.
onnxruntime runs the exported int8 graphs at roughly 2-3x the CPU speed of
torch fp32 and about a quarter of the memory, with an embedding-quality
difference under 1% - measured on this project, not assumed.

Both models are loaded once per process (ADR-023 single worker). Inference is
CPU-bound, so it runs in a worker thread behind a semaphore: without that, a
burst of uploads would starve the event loop and every other request would
stall behind the tokenizer.
"""

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

# One (session, tokenizer) per model directory, built under a lock because two
# coroutines can race on the first request after a cold start.
_lock = threading.Lock()
_models: dict[str, tuple[object, object]] = {}
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        from backend.config import get_settings

        _semaphore = asyncio.Semaphore(max(1, get_settings().local_inference_concurrency))
    return _semaphore


def _load(model_dir: str):
    """Load the exported ONNX graph plus its tokenizer, once per process."""
    with _lock:
        cached = _models.get(model_dir)
        if cached is not None:
            return cached
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover - image build decides this
            raise RuntimeError(
                "onnxruntime/transformers are missing; install the local-ml extra."
            ) from exc
        from pathlib import Path

        path = Path(model_dir)
        graph = path / "model.onnx"
        if not graph.exists():
            raise RuntimeError(f"no ONNX graph at {graph}.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 0  # onnxruntime may use every core
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(
            str(graph), sess_options=options, providers=["CPUExecutionProvider"]
        )
        tokenizer = AutoTokenizer.from_pretrained(str(path))
        _models[model_dir] = (session, tokenizer)
        logger.info("loaded ONNX model from %s", model_dir)
        return _models[model_dir]


def _infer(model_dir: str, texts: list[str], pairs: bool, max_length: int, batch_size: int):
    """Run the graph over texts (or query/document pairs); returns a flat array."""
    import numpy as np

    session, tokenizer = _load(model_dir)
    accepted = {item.name for item in session.get_inputs()}
    rows = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        if pairs:
            encoded = tokenizer(
                [item[0] for item in chunk],
                [item[1] for item in chunk],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
        else:
            encoded = tokenizer(
                chunk,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
        # int8 exports often drop token_type_ids; feeding an input the graph
        # does not declare is a hard onnxruntime error, so filter to accepted.
        feed = {
            name: np.asarray(value)
            for name, value in encoded.items()
            if name in accepted and name != "token_type_ids"
        }
        rows.append(np.asarray(session.run(None, feed)[0]))
    return np.concatenate(rows, axis=0)


def _embed_sync(model_dir: str, texts: list[str], max_length: int, batch_size: int):
    """Return unit vectors. bge-m3 uses CLS pooling, not mean pooling."""
    import numpy as np

    hidden = _infer(model_dir, texts, False, max_length, batch_size)
    pooled = hidden[:, 0] if hidden.ndim == 3 else hidden
    pooled = pooled.astype(np.float32)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return [[float(value) for value in row] for row in (pooled / norms)]


def _score_sync(model_dir: str, pairs: list[list[str]], max_length: int, batch_size: int):
    raw = _infer(model_dir, pairs, True, max_length, batch_size)
    return [float(value) for value in raw.reshape(-1)]


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with the local ONNX model; returns unit vectors."""
    from backend.config import get_settings

    settings = get_settings()
    async with _get_semaphore():
        return await asyncio.to_thread(
            _embed_sync,
            settings.embedding_onnx_dir,
            texts,
            settings.embedding_onnx_max_tokens,
            settings.local_inference_batch_size,
        )


async def score(query: str, documents: list[str]) -> list[float]:
    """Score query/document pairs with the local cross-encoder, higher is better."""
    from backend.config import get_settings

    settings = get_settings()
    pairs = [[query, document] for document in documents]
    async with _get_semaphore():
        return await asyncio.to_thread(
            _score_sync,
            settings.rerank_onnx_dir,
            pairs,
            settings.rerank_onnx_max_tokens,
            settings.local_inference_batch_size,
        )
