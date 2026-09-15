"""Generate the HiveOS test corpus: every supported format at several sizes.

Written to a local folder, then uploaded through the real API. Sizes are chosen
to straddle the boundaries the pipeline actually cares about: the 1 MB nginx
cliff that used to exist, the 25 MB app cap, and the OCR minimum width.
"""

import os
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "corpus"
OUT.mkdir(exist_ok=True)

FA = "پروژه قناری شناسه QNR-7741 بودجه ۹۸ میلیارد ریال دکتر آرمان رهگذر "
SENT = (
    "این سند بخشی از دانش سازمان است و برای آزمون بارگذاری ساخته شده. "
    "قرارداد پشتیبانی سالانه با تأمین‌کننده تک‌منبع قطعه XR-9 تمدید شد. "
)

# Font search order. Tahoma carries Persian glyphs; the reportlab built-ins do
# not, so a PDF drawn with Helvetica would render the corpus text as blanks.
_FA_FONTS = ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/arial.ttf")


def text_body(target_bytes: int) -> str:
    """Persian filler whose UTF-8 size reaches target_bytes."""
    parts: list[str] = []
    n = 0
    while n < target_bytes:
        s = SENT + FA + str(n % 997)
        parts.append(s)
        n += len(s.encode("utf-8")) + 1
    return "\n".join(parts)


def w(name: str, data: bytes | str) -> Path:
    p = OUT / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    print(f"{p.stat().st_size:>10,}  {name}")
    return p


def _first_existing(paths: tuple[str, ...]) -> str | None:
    return next((f for f in paths if os.path.exists(f)), None)


# ---- plain / markup ----
for kb in (1, 50, 500, 2000, 6000):
    w(f"متنی-{kb}KB.txt", text_body(kb * 1024))
w("ساختار.md", "# قرارداد قناری\n\n" + text_body(20_000))
w(
    "صفحه.html",
    '<!doctype html><html lang=fa><meta charset=utf-8><body><h1>'
    + "پروژه قناری</h1><p>"
    + text_body(30_000)
    + "</p></body></html>",
)
json_items = ",".join(f'{{"i":{i},"v":"{SENT[:30]}"}}' for i in range(2000))
w("داده.json", '{"project":"قناری","code":"QNR-7741","items":[' + json_items + "]}")
w("جدول.csv", "ردیف,شرح,مبلغ\n" + "\n".join(f"{i},{SENT[:40]},{i * 1000}" for i in range(3000)))
yaml_items = "\n".join(f"  - id: {i}\n    note: {SENT[:30]}" for i in range(1000))
w("تنظیمات.yaml", "project: قناری\ncode: QNR-7741\nitems:\n" + yaml_items)

# ---- docx ----
for tag, paras in (("کوچک", 20), ("متوسط", 400), ("بزرگ", 4000)):
    d = Document()
    d.add_heading("پروژه قناری", 0)
    d.add_paragraph("شناسه QNR-7741 — بودجه ۹۸ میلیارد ریال")
    for _ in range(paras):
        d.add_paragraph(SENT + FA)
    t = d.add_table(rows=5, cols=3)
    for row in t.rows:
        for cell in row.cells:
            cell.text = "XR-9"
    d.save(OUT / f"گزارش-{tag}.docx")

# ---- xlsx ----
for tag, rows in (("کوچک", 50), ("بزرگ", 20000)):
    wb = Workbook()
    ws = wb.active
    ws.title = "بودجه"
    ws.append(["ردیف", "شرح", "مبلغ", "تاریخ"])
    for i in range(rows):
        ws.append([i, SENT[:60], i * 1000, "۱۴۰۵/۰۳/۱۱"])
    wb.save(OUT / f"بودجه-{tag}.xlsx")

# ---- pptx ----
for tag, slides in (("کوچک", 5), ("بزرگ", 120)):
    pr = Presentation()
    for i in range(slides):
        s = pr.slides.add_slide(pr.slide_layouts[1])
        s.shapes.title.text = f"پروژه قناری {i}"
        s.placeholders[1].text = SENT + FA
    pr.save(OUT / f"ارائه-{tag}.pptx")

# ---- pdf (text) ----
font = "Helvetica"
# A missing or unreadable TTF must leave the built-in font in place rather than
# abort the run: the corpus is still useful without Persian PDF glyphs.
_pdf_font = _first_existing(_FA_FONTS)
if _pdf_font:
    try:
        pdfmetrics.registerFont(TTFont("FA", _pdf_font))
        font = "FA"
    except Exception:  # noqa: BLE001 - fall back to Helvetica
        pass
for tag, pages in (("کوچک", 2), ("متوسط", 40), ("بزرگ", 400)):
    c = canvas.Canvas(str(OUT / f"گزارش-{tag}.pdf"), pagesize=A4)
    for p in range(pages):
        c.setFont(font, 11)
        c.drawString(50, 780, f"پروژه قناری صفحه {p + 1}")
        y = 750
        for line in text_body(2600).split("\n")[:45]:
            c.drawString(50, y, line[:95])
            y -= 15
        c.showPage()
    c.save()

# ---- images (OCR path) ----
fnt = None
_img_font = _first_existing(("C:/Windows/Fonts/tahoma.ttf",))
if _img_font:
    fnt = ImageFont.truetype(_img_font, 28)


def img(name: str, w_: int, h_: int, mode: str = "RGB") -> None:
    im = Image.new(mode, (w_, h_), "white")
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.text((40, 60 + i * 60), f"پروژه قناری QNR-7741 line {i}", fill="black", font=fnt)
    p = OUT / name
    im.save(p)
    print(f"{p.stat().st_size:>10,}  {name}")


img("اسکن-کوچک.png", 600, 400)  # below OCR_MIN_WIDTH
img("اسکن-متوسط.png", 1400, 1000)  # above
img("تصویر-بزرگ.jpg", 3000, 2200)
img("نمای-وب.webp", 1200, 900)
img("سیاه-سفید.bmp", 1600, 1200)
img("تصویر.tiff", 1800, 1300)

# ---- oversized (must be refused cleanly) ----
w("بزرگ-۲۶مگ.txt", text_body(26 * 1024 * 1024))
print("\n--- total ---")
files = sorted(OUT.iterdir())
print(f"{len(files)} files, {sum(f.stat().st_size for f in files) / 1024 / 1024:.1f} MB")
