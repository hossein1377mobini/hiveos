"""OCR page handling: sizing, transparency, rotation and multi-page scans.

The image pipeline was verified against staging with real files, which found
three defects that a status code alone could not:

  * a small image (a phone screenshot, a pasted crop) was passed to tesseract at
    its native size and read as noise - measured 0.717 vs 0.882 once scaled;
  * an RGBA image lost its transparent background to black, because tesseract
    reads alpha as ink;
  * a multi-page TIFF had only its first frame read, and the asset was still
    reported ready, so the missing pages were invisible.

Tesseract itself is not installed on a developer machine or in CI, so the engine
is stubbed here and only our own page preparation is asserted. The end-to-end
behaviour was confirmed on staging.
"""

import sys
import types

from PIL import Image

from backend.knowledge import classify
from backend.knowledge.classify import _OCR_TARGET_WIDTH, _extract_ocr, _ocr_page


def test_small_image_is_scaled_up_into_the_readable_band():
    """Below the band tesseract reads noise; the size must actually change."""
    page = _ocr_page(Image.new("RGB", (300, 200), "white"))
    assert page.width == _OCR_TARGET_WIDTH
    # Aspect ratio is preserved, or the glyphs shear and accuracy drops further.
    assert page.height == int(200 * (_OCR_TARGET_WIDTH / 300))


def test_image_already_in_the_band_is_left_alone():
    """Upscaling a crisp screenshot measurably *lowered* accuracy (0.956 ->
    0.912 at 3x), so a page at or above the threshold must not be resized."""
    page = _ocr_page(Image.new("RGB", (1400, 760), "white"))
    assert (page.width, page.height) == (1400, 760)


def test_transparent_background_becomes_white_not_black():
    """An RGBA logo on transparency was read as a block of stray glyphs."""
    rgba = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    page = _ocr_page(rgba)
    assert page.mode == "RGB"
    # A fully transparent pixel must end up white: black ink was the bug.
    assert page.getpixel((5, 5)) == (255, 255, 255)


def test_exif_rotation_is_applied():
    """A phone photo stores rotation in EXIF; a sideways page reads as noise."""
    # Sized so that the rotation lands on the scaling threshold: a smaller
    # source would be scaled up afterwards and hide whether EXIF was applied.
    wide = Image.new("RGB", (2000, 1000), "white")
    exif = wide.getexif()
    exif[274] = 6  # Orientation: rotate 90 degrees
    page = _ocr_page(wide)
    assert (page.width, page.height) == (1000, 2000), "EXIF rotation was ignored"


def _stub_tesseract(monkeypatch, seen):
    """Replace pytesseract with a recorder; classify imports it lazily.

    shutil.which is stubbed too: _extract_ocr refuses to run without the
    binary, which is what stops a misconfigured deployment from failing
    silently. The engine is absent here, so that guard is satisfied explicitly
    rather than by installing tesseract in CI.
    """
    fake = types.ModuleType("pytesseract")

    def image_to_string(image, lang=None, **kwargs):
        seen.append((image.width, image.height))
        return f"page-{len(seen)}"

    fake.image_to_string = image_to_string
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(classify.shutil, "which", lambda name: "/usr/bin/tesseract")


def test_every_frame_of_a_multipage_tiff_is_read(tmp_path, monkeypatch):
    """Only frame one was read before, and the asset still came back ready."""
    frames = [Image.new("RGB", (300, 200), c) for c in ("white", "gray", "white")]
    path = tmp_path / "scan.tif"
    frames[0].save(path, save_all=True, append_images=frames[1:])

    seen = []
    _stub_tesseract(monkeypatch, seen)
    text = _extract_ocr(path)

    assert len(seen) == 3, "every page of the scan must reach the engine"
    assert text == "page-1\npage-2\npage-3"
    # The small frames must still have been scaled on the way through.
    assert all(width == _OCR_TARGET_WIDTH for width, _ in seen)


def test_single_page_image_reads_once(tmp_path, monkeypatch):
    """n_frames handling must not double-read an ordinary image."""
    path = tmp_path / "one.png"
    Image.new("RGB", (1400, 700), "white").save(path)

    seen = []
    _stub_tesseract(monkeypatch, seen)
    text = _extract_ocr(path)

    assert len(seen) == 1
    assert text == "page-1"
