"""WAVE-3B: local chunk -> embed -> index pipeline for US-007.

On-prem only (ADR-019): embeddings are generated locally with ``fastembed``
(intfloat/multilingual-e5-large, 1024-dim, multilingual incl. Persian) — NO
Avalai tokens are consumed for embedding. The model is downloaded once and
cached; the process keeps a lazy singleton (thread-safe).

Seam used by ``process_job``:
    text = read_document_text(path, fmt)
    chunks = chunk_text(text, chunk_size, overlap)
    vectors = embed_texts(chunks)          # list[list[float]] each len == EMBED_DIM
    -> caller writes DocumentChunk rows (embedding Vector(EMBED_DIM)).
"""

import math
import os
import re
import threading

from app.config import get_settings

EMBED_MODEL = "intfloat/multilingual-e5-large"
EMBED_DIM = 1024

# S1-11: intfloat/multilingual-e5-large is a prefix-carrying E5 model — text must
# be prefixed with "passage: " (documents to index) or "query: " (search query) for
# the model to inhabit the correct side of its trained embedding space. fastembed
# does NOT add these prefixes automatically (PooledEmbedding.embed is pass-through),
# so we apply them here at embed time.
_PASSAGE_PREFIX = "passage: "
_QUERY_PREFIX = "query: "

_lock = threading.Lock()
_model = None

_TEXT_SPLIT_RE = re.compile(r"[ \t\r\n\f\v]+")


def _get_model():
    """Lazy, thread-safe singleton of the local embedding model."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                _model = TextEmbedding(model_name=EMBED_MODEL)
    return _model


def read_document_text(path: str, fmt: str) -> str:
    """Extract plain text from a supported file (txt|md|pdf|docx)."""
    fmt = (fmt or "").lower()
    if fmt == "txt":
        return _read_plaintext(path)
    if fmt == "md":
        return _read_plaintext(path)
    if fmt == "pdf":
        return _read_pdf(path)
    if fmt == "docx":
        return _read_docx(path)
    raise ValueError(f"unsupported format: {fmt}")


def _read_plaintext(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _read_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    # S1-08: image/scan-only PDFs yield no text layer (pypdf returns "" on every
    # page). A "ready" document with zero chunks is wrong — reject with an explicit
    # reason so the worker marks the Document ``failed`` (not ``ready``).
    if not text.strip():
        raise ValueError(
            "no extractable text (image/scanned PDF without a text layer); OCR is not supported"
        )
    return text


def _read_docx(path: str) -> str:
    from docx import Document as DocxDocument

    doc = DocxDocument(path)
    parts = [p.text for p in doc.paragraphs if p.text]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """Character-based overlap chunking, splitting preferentially at newlines.

    Works for any script (incl. Persian — no word-boundary dependency). Cheap and
    deterministic. Empty/whitespace-only chunks are dropped.
    """
    if not text or not text.strip():
        return []
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError(f"invalid chunk config: chunk_size={chunk_size}, overlap={overlap}")
    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if start + chunk_size >= len(text):
            break
    return chunks


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector to unit length (E5 expects cosine = dot on unit vectors)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:  # degenerate zero vector — leave as-is rather than NaN
        return vec
    return [x / norm for x in vec]


def _embed(chunks: list[str], prefix: str) -> list[list[float]]:
    """Embed ``chunks`` (each prefixed) -> list of L2-normalized ``EMBED_DIM`` vectors."""
    if not chunks:
        return []
    model = _get_model()
    # S1-11: apply the E5 side prefix (passage for documents, query for search) at
    # embed time — the model was trained with these and fastembed won't add them.
    prefixed = [f"{prefix}{c}" for c in chunks]
    vectors = []
    for vec in model.embed(prefixed):
        dims = list(vec)
        if len(dims) != EMBED_DIM:
            raise RuntimeError(
                f"embedding dim {len(dims)} != expected {EMBED_DIM}; "
                f"model/config drift (DocumentChunk.embedding is Vector({EMBED_DIM}))"
            )
        # S1-11: L2-normalize so cosine similarity (the HNSW operator_class) is
        # exact. fastembed's PooledEmbedding does NOT normalize E5 outputs.
        vectors.append(_l2_normalize(dims))
    return vectors


def embed_texts(chunks: list[str]) -> list[list[float]]:
    """Embed document/passage chunks -> list of ``EMBED_DIM`` L2-normalized vectors."""
    return _embed(chunks, _PASSAGE_PREFIX)


def embed_queries(queries: list[str]) -> list[list[float]]:
    """Embed search queries -> list of ``EMBED_DIM`` L2-normalized vectors."""
    return _embed(queries, _QUERY_PREFIX)


def embedding_dim() -> int:
    _get_model()  # ensure loaded
    return EMBED_DIM


def supported_format(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in (".txt", ".md", ".pdf", ".docx")


def default_chunk_config() -> dict:
    s = get_settings()
    return {"chunk_size": s.ingestion_chunk_size, "overlap": s.ingestion_chunk_overlap}
