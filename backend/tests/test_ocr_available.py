"""The image pipeline must be able to run OCR in the deployed image.

Found by the real-data test: all six advertised image formats (jpg/jpeg/png/
tif/tiff/bmp/webp) were classified as image -> ocr and then stuck at "queued"
forever. classify._extract_ocr refuses to run without the tesseract binary, so
the asset stayed queued and was never searchable - silently, because a missing
engine is recorded as "needs review" rather than an error the user sees.

The fix has two halves that must stay together: the binary in the image, and the
pytesseract binding in the runtime dependencies. Tesseract is not installed on a
developer machine or in CI, so this cannot assert the engine works here; it
asserts the deployment still carries it. The live check that images actually
become ready was done against staging.
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
DOCKERFILE = REPO / "infrastructure" / "api.Dockerfile"
PYPROJECT = BACKEND / "pyproject.toml"


def test_image_installs_the_ocr_engine_and_the_persian_pack():
    """Without the binary every image asset is queued forever."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "tesseract-ocr" in text, (
        "the API image must install tesseract-ocr; without it classify.py raises "
        "OCR_UNAVAILABLE and image assets never reach ready"
    )
    # The corpus text is Persian. eng alone returns nothing usable for it, so a
    # build that dropped the fas pack would look fine and produce empty text.
    assert "tesseract-ocr-fas" in text, (
        "the Persian language pack must be installed; image text is Persian and "
        "eng-only extraction returns empty text"
    )


def test_pytesseract_binding_is_a_runtime_dependency():
    """The binary alone is not enough - classify.py imports pytesseract."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "pytesseract" in text, (
        "pytesseract must be a runtime dependency; it is imported inside "
        "_extract_ocr at extraction time, not at import time, so a missing "
        "binding only shows up when a real image is processed"
    )
