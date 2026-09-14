"""Asset classification + pipeline routing (US-205/US-206, T-S2-4).

FR-001: the real type comes from Magic Bytes, never from the extension
(scenario 4: a fake report.pdf with image bytes). Routes follow the US-205
v0.1 table; archives/unknown types land in the review queue untouched.
Extraction (US-206) runs right after classification inside the worker.
Folder assets resolve their physical file from the source path + rel_path.
"""

import csv
import io
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from backend.api_errors import ApiError
from backend.models import KnowledgeAsset

ASSET_TYPES = ("text", "pdf", "office", "spreadsheet", "image", "code", "archive", "unknown")
PIPELINES = (
    "text_parser",
    "pdf_parser",
    "office_parser",
    "spreadsheet_parser",
    "ocr",
    "review_queue",
)

_TEXT_EXTENSIONS = {"txt", "md"}
_CODE_EXTENSIONS = {"py", "js", "ts", "sh", "json", "yml", "yaml", "sql", "css"}


def _resolve_path(asset: KnowledgeAsset, source_path: str | None) -> Path | None:
    if asset.storage_path:
        candidate = Path(asset.storage_path)
        if candidate.is_file():
            return candidate
    if asset.rel_path and source_path:
        candidate = Path(source_path) / asset.rel_path
        if candidate.is_file():
            return candidate
    return None


def _magic(path: Path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(16)


# E: OOXML packages are identified by their main part, not by a directory
# prefix - a single smuggled "ppt/x" member used to masquerade as a presentation
# (and could disagree with what python-docx/python-pptx then actually parsed).
_OOXML_TEXT_PART = "word/document.xml"
_OOXML_SLIDE_PART = "ppt/presentation.xml"
_OOXML_SHEET_PART = "xl/workbook.xml"


def _sniff(path: Path) -> str:
    """Magic-byte sniffing -> one of ASSET_TYPES (US-205 FR-001)."""
    magic = _magic(path)
    if magic.startswith(b"%PDF"):
        return "pdf"
    if magic.startswith(b"PK\x03\x04"):
        # zip container: office packages carry word/ ppt/ xl/ prefixes
        try:
            with zipfile.ZipFile(path) as bundle:
                names = bundle.namelist()
        except Exception:  # noqa: BLE001 - broken zip falls through to unknown
            return "unknown"
        if any(name in (_OOXML_TEXT_PART, _OOXML_SLIDE_PART) for name in names):
            return "office"
        if any(name == _OOXML_SHEET_PART for name in names):
            return "spreadsheet"
        return "archive"  # plain zip -> extraction out of scope in v0.1 (US-204)
    if magic.startswith((b"\xff\xd8", b"\x89PNG", b"II*\x00", b"MM\x00*", b"BM")):
        return "image"
    if magic.startswith(b"RIFF") and len(magic) >= 12 and magic[8:12] == b"WEBP":
        return "image"
    if magic.startswith(b"PK"):
        return "archive"  # plain zip -> extraction out of scope in v0.1 (US-204)
    extension = path.suffix.lstrip(".").lower()
    if extension in _TEXT_EXTENSIONS:
        return "text"
    if extension in _CODE_EXTENSIONS:
        return "code"
    if extension == "csv":
        return "spreadsheet"
    return "unknown"


def route_pipeline(asset_type: str) -> str:
    """US-205 pipeline table (v0.1 active rows)."""
    return {
        "pdf": "pdf_parser",  # text-layer vs OCR decided at extraction time
        "office": "office_parser",
        "spreadsheet": "spreadsheet_parser",
        "image": "ocr",
        "text": "text_parser",
        "code": "text_parser",
    }.get(asset_type, "review_queue")


def classify_asset(asset: KnowledgeAsset, source_path: str | None = None) -> dict:
    """US-205 FR-001..FR-005: sniff, route, persist; returns the verdict."""
    path = _resolve_path(asset, source_path)
    if path is None:
        raise ApiError(400, "ASSET_FILE_MISSING", "The asset file cannot be found.")
    asset_type = _sniff(path)
    asset.asset_type = asset_type
    asset.pipeline = route_pipeline(asset_type)
    asset.classified_at = datetime.now(UTC)
    return {"asset_type": asset_type, "pipeline": asset.pipeline}


def extract_text(asset: KnowledgeAsset, source_path: str | None = None) -> str:
    """US-206: route to the right extractor; empty PDF text = OCR (scenario 2)."""
    path = _resolve_path(asset, source_path)
    if path is None:
        raise ApiError(400, "ASSET_FILE_MISSING", "The asset file cannot be found.")
    if asset.pipeline == "text_parser":
        return _extract_text_file(path)
    if asset.pipeline == "pdf_parser":
        return _extract_pdf(path)
    if asset.pipeline == "office_parser":
        return _extract_office(path)
    if asset.pipeline == "spreadsheet_parser":
        return _extract_spreadsheet(path)
    if asset.pipeline == "ocr":
        return _extract_ocr(path)
    raise ApiError(400, "REVIEW_QUEUE", "This asset type needs manual review.")


def _extract_text_file(path: Path) -> str:
    # E: Postgres rejects NUL in text columns - a binary file that sniffs as a
    # text type made the whole worker batch answer "invalid byte sequence".
    return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    # E: PdfReader keeps the file open; the worker runs this once per asset per
    # scan, so leaked handles piled up until the process hit its limit.
    try:
        with open(path, "rb") as handle:
            reader = PdfReader(handle)
            pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - corrupt PDF = failed extraction
        raise ApiError(400, "EXTRACTION_FAILED", "The PDF could not be read.") from exc
    text = "\n".join(pages).strip()
    if not text:
        # scanned PDF -> the OCR pipeline takes over (US-205 scenario 2)
        return _extract_ocr(path)
    return text


def _extract_office(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as bundle:
            names = bundle.namelist()
        if _OOXML_SLIDE_PART in names:
            from pptx import Presentation

            presentation = Presentation(str(path))
            return "\n".join(
                shape.text
                for slide in presentation.slides
                for shape in slide.shapes
                if shape.has_text_frame
            ).strip()
        from docx import Document

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt office file = failed extraction
        raise ApiError(400, "EXTRACTION_FAILED", "The document could not be read.") from exc


def _extract_spreadsheet(path: Path) -> str:
    if path.suffix.lower() == ".csv":
        text = path.read_text(encoding="utf-8", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join(",".join(row) for row in rows)
    from openpyxl import load_workbook

    # E: a read_only workbook holds its file handle until close().
    workbook = load_workbook(str(path), read_only=True, data_only=True)
    try:
        lines: list[str] = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if value is None else str(value) for value in row]
                if any(cells):
                    lines.append(",".join(cells))
        return "\n".join(lines)
    finally:
        workbook.close()


# Tesseract resolves text reliably around a 1400px page width, and accuracy
# falls away on both sides of that band. Measured on a Persian page scored
# character-for-character against ground truth:
#
#   render width   1x      2x      3x
#   1400px         0.956   0.936   0.912   <- upscaling a large page hurts
#    560px         0.911   0.964   0.890
#    300px         0.717   0.848   0.882   <- a small page badly needs it
#
# So small images are scaled up into the band and large ones are left alone.
# Upscaling everything to a fixed 300 DPI - the usual advice - scored *worse*
# than the untouched image on every screenshot tested, because these are
# already-crisp UI renders rather than scanned paper.
_OCR_TARGET_WIDTH = 1400
_OCR_MIN_WIDTH = 1000


def _ocr_page(image):
    """Correct one page for rotation, transparency and size."""
    from PIL import Image, ImageOps

    # A phone photo stores its rotation in EXIF; ignoring it hands tesseract a
    # sideways page, which reads as noise rather than failing.
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        # Transparent pixels render as black to tesseract, so an RGBA logo on a
        # transparent background was read as a block of stray glyphs.
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.split()[-1])
        image = canvas
    elif image.mode != "RGB":
        image = image.convert("RGB")
    if image.width < _OCR_MIN_WIDTH:
        scale = _OCR_TARGET_WIDTH / image.width
        image = image.resize(
            (int(image.width * scale), int(image.height * scale)), Image.LANCZOS
        )
    return image


def _extract_ocr(path: Path) -> str:
    if shutil.which("tesseract") is None:
        raise ApiError(
            503,
            "OCR_UNAVAILABLE",
            "OCR engine is not installed on this server; the asset needs review.",
        )
    import pytesseract
    from PIL import Image

    pages: list[str] = []
    with Image.open(path) as source:
        # A multi-page TIFF is a scanned document. Reading only the open frame
        # silently dropped every page after the first, and the asset still came
        # back "ready" - so the loss was invisible.
        frames = getattr(source, "n_frames", 1)
        for index in range(frames):
            if frames > 1:
                source.seek(index)
            # copy() detaches the frame: seeking the shared handle invalidates
            # the previous frame, and _ocr_page returns a new image anyway.
            with _ocr_page(source.copy()) as page:
                pages.append(pytesseract.image_to_string(page, lang="fas+eng"))
    return "\n".join(pages).strip()

