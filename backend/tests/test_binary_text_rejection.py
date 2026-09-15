"""Binary files uploaded under a text extension must not be indexed.

Regression for the search outage found on staging 2026-09-15. A load-test
corpus uploaded random bytes named .txt; _extract_text_file decoded them with
errors="replace", so each file became thousands of chunks of U+FFFD mojibake.
Those embeddings sit near the mean of the vector space, which makes them close
to *every* query, so they crowded the genuinely relevant chunks out of the
candidate pool. Semantic search then answered "nothing found" for content that
was indexed and correct, and the AI never cited a source.
"""

import pytest

from backend.api_errors import ApiError
from backend.knowledge.classify import _extract_text_file, _looks_binary


def test_random_bytes_are_detected_as_binary(tmp_path):
    path = tmp_path / "random.txt"
    # Deterministic pseudo-random bytes, the same shape the load corpus had.
    path.write_bytes(bytes((i * 137 + 41) % 256 for i in range(8192)))
    assert _looks_binary(path) is True


def test_openpgp_and_zip_headers_are_detected(tmp_path):
    openpgp = tmp_path / "key.txt"
    openpgp.write_bytes(b"\x99\x0d\x04\x00" + bytes(range(256)) * 8)
    assert _looks_binary(openpgp) is True

    zipped = tmp_path / "archive.txt"
    zipped.write_bytes(b"PK\x03\x04" + bytes(200))
    assert _looks_binary(zipped) is True


def test_nul_byte_alone_marks_binary(tmp_path):
    path = tmp_path / "nul.txt"
    path.write_bytes(b"starts as text\x00then binary")
    assert _looks_binary(path) is True


def test_real_text_in_several_languages_is_not_binary(tmp_path):
    persian = tmp_path / "fa.txt"
    persian.write_text(
        "پروژه قناری یک پروژه ملی است. بودجه مصوب نود و هشت میلیارد ریال است.\n" * 40,
        encoding="utf-8",
    )
    assert _looks_binary(persian) is False

    mixed = tmp_path / "mixed.txt"
    mixed.write_text(
        "Report \u2014 2026\nSch\u00f6n, 98% \u2713\nd\u00e9tails\n" * 40, encoding="utf-8"
    )
    assert _looks_binary(mixed) is False


def test_one_bad_byte_does_not_reject_a_text_file(tmp_path):
    path = tmp_path / "mostly-text.txt"
    path.write_bytes(b"ordinary ascii prose, many words, " * 100 + b"\xff")
    assert _looks_binary(path) is False


def test_empty_file_is_not_binary(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    assert _looks_binary(path) is False


def test_extract_text_file_refuses_binary_instead_of_returning_mojibake(tmp_path):
    path = tmp_path / "fake.txt"
    path.write_bytes(bytes((i * 91 + 7) % 256 for i in range(4096)))
    with pytest.raises(ApiError) as exc:
        _extract_text_file(path)
    assert exc.value.code == "EXTRACTION_FAILED"
    # The whole point: no U+FFFD mojibake ever reaches the embedding model.
    assert "\ufffd" not in str(exc.value)


def test_extract_text_file_still_returns_real_text(tmp_path):
    path = tmp_path / "real.txt"
    path.write_text("فهرست پروژه\nشرح,مقدار\n", encoding="utf-8")
    assert "فهرست" in _extract_text_file(path)
