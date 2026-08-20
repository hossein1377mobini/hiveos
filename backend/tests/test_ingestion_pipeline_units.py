"""WAVE-3B — unit tests for the real chunk -> embed -> index pipeline primitives.

Covers ``chunk_text`` (overlap contiguity, size cap, empty/whitespace/Persian
determinism), ``read_document_text`` (txt/md/docx + malformed pdf), and
``embed_texts`` (one real local embed -> 1024-dim, cached model, no network).

These are pure functions — no DB, no app, no network. The single embed test
loads the cached multilingual-e5-large model (first load ~10-30s), after which
the lazy singleton is reused by the integration tests.
"""

from itertools import pairwise

import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter
from pypdf.errors import PyPdfError

from app.services import ingestion_pipeline
from app.services.ingestion_pipeline import (
    EMBED_DIM,
    _l2_normalize,
    chunk_text,
    embed_queries,
    embed_texts,
    read_document_text,
)


def _no_whitespace_text(length: int) -> str:
    """A deterministic string with no whitespace so ``.strip()`` is identity at
    every chunk boundary (keeps overlap-contiguity assertions exact)."""
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return (alphabet * ((length // len(alphabet)) + 1))[:length]


# ----------------------------------------------------------------- chunk_text


def test_chunk_text_overlap_is_contiguous():
    text = _no_whitespace_text(260)
    chunk_size, overlap = 10, 4
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    assert len(chunks) > 1
    # Every adjacent pair shares exactly `overlap` trailing/leading characters.
    for prev, nxt in pairwise(chunks):
        assert prev[-overlap:] == nxt[:overlap]


def test_chunk_text_respects_chunk_size():
    text = _no_whitespace_text(1500)
    chunk_size, overlap = 512, 64
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    assert len(chunks) >= 2  # must actually split
    assert all(len(c) <= chunk_size for c in chunks)
    # Covers the whole input: (n-1)*step + chunk_size >= len(text) (contiguity).
    step = chunk_size - overlap
    assert (len(chunks) - 1) * step + chunk_size >= len(text)


def test_chunk_text_empty_and_whitespace_return_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   \n\t\r   ") == []
    assert chunk_text(None) == []  # type: ignore[arg-type] — sentinel guard path


def test_chunk_text_deterministic_and_persian_friendly():
    persian = "سلامدنیااینیکمتنفارسیبرایآزمونچانکینگاستکهبدونفاصلهمینویسیم" * 6
    first = chunk_text(persian)
    second = chunk_text(persian)

    assert first == second
    assert len(first) >= 1
    assert all(c.strip() == c for c in first)  # no boundary stripping surprises
    # Deterministic with default config too (no word-boundary/`\w` dependency).
    assert chunk_text(persian) == chunk_text(persian, chunk_size=512, overlap=64)


# ---------------------------------------------------------- read_document_text


def test_read_document_text_txt(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("hello hiveos\nline two", encoding="utf-8")

    assert read_document_text(str(path), "txt") == "hello hiveos\nline two"


def test_read_document_text_md(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome **markdown** body.\n", encoding="utf-8")

    text = read_document_text(str(path), "md")

    assert "# Title" in text
    assert "**markdown**" in text


def test_read_document_text_docx(tmp_path):
    path = tmp_path / "report.docx"
    doc = DocxDocument()
    doc.add_paragraph("سلام دنیا — this is a docx paragraph.")
    doc.save(str(path))

    text = read_document_text(str(path), "docx")

    assert "سلام دنیا" in text
    assert "docx paragraph" in text


def test_read_document_text_malformed_pdf_raises(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is definitely not a pdf" * 8)

    with pytest.raises(PyPdfError):  # malformed PDF -> pypdf error, not a silent empty string
        read_document_text(str(path), "pdf")


def test_read_document_text_scanned_pdf_rejects(tmp_path):
    """S1-08: an image/scan-only PDF (no text layer -> pypdf yields '') is rejected
    with an explicit reason instead of silently returning an empty string."""
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)  # a page with no text operators
    with open(path, "wb") as fh:
        writer.write(fh)

    with pytest.raises(ValueError, match="no extractable text"):
        read_document_text(str(path), "pdf")


# --------------------------------------------------------------- embed_texts


def test_embed_texts_returns_1024_dim_for_persian():
    """Real local embed of a short Persian string -> one 1024-dim float vector.

    Loads the cached multilingual-e5-large model (no network). One test is
    enough: the result of the singleton is what the integration flow uses too.
    """
    vectors = embed_texts(["سلام دنیا این یک تست امبدینگ است"])

    assert len(vectors) == 1
    assert len(vectors[0]) == EMBED_DIM == 1024
    assert all(isinstance(x, float) for x in vectors[0])


def test_l2_normalize_unit_norm():
    assert sum(x * x for x in _l2_normalize([3.0, 4.0])) == pytest.approx(1.0)
    assert _l2_normalize([0.0, 0.0]) == [0.0, 0.0]  # degenerate -> unchanged, no NaN


class _StubModel:
    """Capturing stub for the embedding model (no ONNX load)."""

    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed(self, texts: list[str]):
        self.inputs.append(list(texts))
        for _ in texts:
            yield [3.0] + [0.0] * (EMBED_DIM - 1)  # blatantly non-unit norm


def test_embed_texts_applies_passage_prefix_and_l2_normalizes(monkeypatch):
    """S1-11: documents are embedded with the E5 ``passage: `` prefix and the raw
    vectors are L2-normalized before they are returned for storage."""
    stub = _StubModel()
    monkeypatch.setattr(ingestion_pipeline, "_get_model", lambda: stub)

    vectors = embed_texts(["سلام دنیا", "hello world"])

    assert stub.inputs == [["passage: سلام دنیا", "passage: hello world"]]
    assert len(vectors) == 2
    for v in vectors:
        assert sum(x * x for x in v) == pytest.approx(1.0)  # L2 unit norm
        assert v[0] == pytest.approx(1.0)


def test_embed_queries_applies_query_prefix(monkeypatch):
    """S1-11: the query side carries the E5 ``query: `` prefix (completing the pair)."""
    stub = _StubModel()
    monkeypatch.setattr(ingestion_pipeline, "_get_model", lambda: stub)

    embed_queries(["یک جستجو"])

    assert stub.inputs == [["query: یک جستجو"]]
