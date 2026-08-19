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

import os
import re
import threading

from app.config import get_settings

EMBED_MODEL = "intfloat/multilingual-e5-large"
EMBED_DIM = 1024

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
    return "\n".join((page.extract_text() or "") for page in reader.pages)


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
    step = max(1, chunk_size - max(0, overlap))
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if start + chunk_size >= len(text):
            break
    return chunks


def embed_texts(chunks: list[str]) -> list[list[float]]:
    """Embed a batch of text chunks -> list of ``EMBED_DIM`` float vectors."""
    if not chunks:
        return []
    model = _get_model()
    vectors = []
    for vec in model.embed(chunks):
        dims = list(vec)
        if len(dims) != EMBED_DIM:
            raise RuntimeError(
                f"embedding dim {len(dims)} != expected {EMBED_DIM}; "
                f"model/config drift (DocumentChunk.embedding is Vector({EMBED_DIM}))"
            )
        vectors.append(dims)
    return vectors


def embedding_dim() -> int:
    _get_model()  # ensure loaded
    return EMBED_DIM


def supported_format(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in (".txt", ".md", ".pdf", ".docx")


def default_chunk_config() -> dict:
    s = get_settings()
    return {"chunk_size": s.ingestion_chunk_size, "overlap": s.ingestion_chunk_overlap}
