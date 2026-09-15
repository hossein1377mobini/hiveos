"""Generate the HiveOS test corpus: every supported format at several sizes.

Written to a local folder, then uploaded through the real API. Sizes are chosen
to straddle the boundaries the pipeline actually cares about: the 1 MB nginx
cliff that used to exist, the 25 MB app cap, and the OCR minimum width.
"""
import os, random, string, struct, zipfile
from pathlib import Path

OUT = Path(__file__).parent / "corpus"
OUT.mkdir(exist_ok=True)

FA = "پروژه قناری شناسه QNR-7741 بودجه ۹۸ میلیارد ریال دکتر آرمان رهگذر "
SENT = ("این سند بخشی از دانش سازمان است و برای آزمون بارگذاری ساخته شده. "
        "قرارداد پشتیبانی سالانه با تأمین‌کننده تک‌منبع قطعه XR-9 تمدید شد. ")

def text_body(target_bytes):
    parts, n = [], 0
    while n < target_bytes:
        s = SENT + FA + str(n % 997)
        parts.append(s); n += len(s.encode("utf-8")) + 1
    return "\n".join(parts)

def w(name, data):
    p = OUT / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    print(f"{p.stat().st_size:>10,}  {name}")
    return p

# ---- plain / markup ----
for kb in (1, 50, 500, 2000, 6000):
    w(f"متنی-{kb}KB.txt", text_body(kb * 1024))
w("ساختار.md", "# قرارداد قناری\n\n" + text_body(20_000))
w("صفحه.html", "<!doctype html><html lang=fa><meta charset=utf-8><body><h1>پروژه قناری</h1><p>" + text_body(30_000) + "</p></body></html>")
w("داده.json", '{"project":"قناری","code":"QNR-7741","items":[' + ",".join('{"i":%d,"v":"%s"}' % (i, SENT[:30]) for i in range(2000)) + ']}')
w("جدول.csv", "ردیف,شرح,مبلغ\n" + "\n".join(f"{i},{SENT[:40]},{i*1000}" for i in range(3000)))
w("تنظیمات.yaml", "project: قناری\ncode: QNR-7741\nitems:\n" + "\n".join(f"  - id: {i}\n    note: {SENT[:30]}" for i in range(1000)))

# ---- docx ----
from docx import Document
for tag, paras in (("کوچک", 20), ("متوسط", 400), ("بزرگ", 4000)):
    d = Document(); d.add_heading("پروژه قناری", 0)
    d.add_paragraph("شناسه QNR-7741 — بودجه ۹۸ میلیارد ریال")
    for i in range(paras): d.add_paragraph(SENT + FA)
    t = d.add_table(rows=5, cols=3)
    for r in t.rows:
        for c in r.cells: c.text = "XR-9"
    d.save(OUT / f"گزارش-{tag}.docx")

# ---- xlsx ----
for tag, rows in (("کوچک", 50), ("بزرگ", 20000)):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "بودجه"
    ws.append(["ردیف", "شرح", "مبلغ", "تاریخ"])
    for i in range(rows): ws.append([i, SENT[:60], i * 1000, "۱۴۰۵/۰۳/۱۱"])
    wb.save(OUT / f"بودجه-{tag}.xlsx")

# ---- pptx ----
from pptx import Presentation
for tag, slides in (("کوچک", 5), ("بزرگ", 120)):
    pr = Presentation()
    for i in range(slides):
        s = pr.slides.add_slide(pr.slide_layouts[1])
        s.shapes.title.text = f"پروژه قناری {i}"
        s.placeholders[1].text = SENT + FA
    pr.save(OUT / f"ارائه-{tag}.pptx")

# ---- pdf (text) ----
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
font = "Helvetica"
for f in ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/arial.ttf"):
    if os.path.exists(f):
        try: pdfmetrics.registerFont(TTFont("FA", f)); font = "FA"; break
        except Exception: pass
for tag, pages in (("کوچک", 2), ("متوسط", 40), ("بزرگ", 400)):
    c = canvas.Canvas(str(OUT / f"گزارش-{tag}.pdf"), pagesize=A4)
    for p in range(pages):
        c.setFont(font, 11); c.drawString(50, 780, f"پروژه قناری صفحه {p+1}")
        y = 750
        for line in text_body(2600).split("\n")[:45]:
            c.drawString(50, y, line[:95]); y -= 15
        c.showPage()
    c.save()

# ---- images (OCR path) ----
from PIL import Image, ImageDraw, ImageFont
fnt = None
for f in ("C:/Windows/Fonts/tahoma.ttf",):
    if os.path.exists(f): fnt = ImageFont.truetype(f, 28); break
def img(name, w_, h_, mode="RGB"):
    im = Image.new(mode, (w_, h_), "white"); d = ImageDraw.Draw(im)
    for i in range(12):
        d.text((40, 60 + i * 60), f"پروژه قناری QNR-7741 line {i}", fill="black", font=fnt)
    p = OUT / name; im.save(p); print(f"{p.stat().st_size:>10,}  {name}")
img("اسکن-کوچک.png", 600, 400)      # below OCR_MIN_WIDTH
img("اسکن-متوسط.png", 1400, 1000)   # above
img("تصویر-بزرگ.jpg", 3000, 2200)
img("نمای-وب.webp", 1200, 900)
img("سیاه-سفید.bmp", 1600, 1200)
img("تصویر.tiff", 1800, 1300)

# ---- oversized (must be refused cleanly) ----
w("بزرگ-۲۶مگ.txt", text_body(26 * 1024 * 1024))
print("\n--- total ---")
files = sorted(OUT.iterdir())
print(f"{len(files)} files, {sum(f.stat().st_size for f in files)/1024/1024:.1f} MB")
