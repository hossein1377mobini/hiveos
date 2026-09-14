"""Report generation (PO request): a requested report becomes a real file.

The PO asked for two things that belong together:

  1. "اضافه شدن ابزارهای مصورسازی برای وقت‌هایی که کاربر درخواست گزارش و این
     موارد می‌کند" - when a user asks for a report, the system should be able to
     show them a chart, not a wall of prose.
  2. "که این فایل ساخته شده هم به فایل‌های کاربر اضافه میشه و فایل داخل خود
     سیستم ساخته میشه" - the generated file joins the user's files, and the file
     is produced inside the system.

So a report here is not a rendered view that disappears on reload. It is a
KnowledgeAsset row plus a file on disk under the organization's upload
directory, which means it shows up in the files list like any other document,
counts against the same quota, and can be read back later.

WHY SELF-CONTAINED HTML

The output format matters more than it looks. A report that is a .docx or a
.pdf cannot be generated without a heavyweight dependency, and one that is a
plain .md loses the charts. A single HTML file with inline CSS and inline SVG
is the one format that:
  - needs no new dependency (the SVG is written by hand here),
  - carries its own charts (no external asset, so the file works when emailed),
  - carries its own styling, so it cannot drift from the design tokens, and
  - is still readable as text if someone opens it in an editor.

The colours below are the literal hex values of the design tokens rather than
var() references. That is deliberate: the CSS custom properties live in the
app's stylesheet, which is not present next to a downloaded file, so a var()
reference would render as nothing. The values are kept in one dict so a palette
change has one place to land.

CSV IS ALSO OFFERED for the same data, because a report someone wants to
re-analyse should not have to be scraped back out of HTML.
"""

import csv
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.models import KnowledgeAsset, Organization

# Design tokens, as literal values. See the module docstring for why these are
# not var() references. Source of truth: frontend/src/styles.css @theme.
PALETTE = {
    "canvas": "#f7f7f4",
    "card": "#ffffff",
    "canvas_soft": "#fafaf7",
    "ink": "#26251e",
    "body": "#5a5852",
    "muted": "#807d72",
    "hairline": "#e6e5e0",
    "hairline_soft": "#efeee8",
    "accent": "#f54e00",
    # The interactive/accent text step, and the error text step, are the AA-safe
    # values from styles.css - not the vivid #f54e00 / #cf2d56. A report is a
    # surface someone prints and reads, so it must clear 4.5:1 like the app does.
    "accent_active": "#a83600",
    "success": "#166b4e",
    "error": "#ba284d",
    "peach": "#dfa88f",
    "mint": "#9fc9a2",
    "sky": "#9fbbe0",
    "violet": "#c0a8dd",
    "amber": "#c08532",
}

MONO_STACK = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"

MAX_REPORT_ROWS = 500


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _escape(text) -> str:
    """HTML-escape. Report content is organization data plus user-supplied
    labels, so this is a real injection boundary, not a formality."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _bars(rows: list[dict], label_key: str, value_key: str, max_bars: int = 12) -> str:
    """Horizontal bars, as inline SVG.

    Horizontal because the labels are Persian and model identifiers - neither
    fits under a vertical bar without rotation.
    """
    top = rows[:max_bars]
    if not top:
        return '<p class="empty">داده‌ای برای نمایش نیست.</p>'
    peak = max(float(row[value_key]) for row in top) or 1.0

    height_each = 34
    height = height_each * len(top) + 8
    width = 640
    label_w = 220
    bar_max = width - label_w - 80

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">']
    for index, row in enumerate(top):
        y = index * height_each + 6
        value = float(row[value_key])
        bar_w = max(2.0, (value / peak) * bar_max)
        label = _escape(row[label_key])[:34]
        shown = _escape(int(value)) if value == int(value) else value
        parts.append(
            f'<text x="{label_w - 12}" y="{y + 15}" font-size="12" '
            f'fill="{PALETTE["body"]}" text-anchor="end">{label}</text>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y + 4}" width="{bar_max}" height="14" rx="4" '
            f'fill="{PALETTE["accent"]}" opacity="0.12"/>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y + 4}" width="{bar_w:.1f}" height="14" rx="4" '
            f'fill="{PALETTE["accent"]}"/>'
        )
        parts.append(
            f'<text x="{width - 6}" y="{y + 15}" font-size="12" '
            f'fill="{PALETTE["muted"]}">{shown}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _sparkline(values: list[float]) -> str:
    if len(values) < 2:
        return ""
    width, height = 640, 60
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{index * step:.1f},{height - 4 - ((value - low) / span) * (height - 8):.1f}"
        for index, value in enumerate(values)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
        f'preserveAspectRatio="none"><polyline points="{points}" fill="none" '
        f'stroke="{PALETTE["accent"]}" stroke-width="2"/></svg>'
    )


def render_html_report(
    *,
    title: str,
    organization_name: str,
    sections: list[dict],
    generated_at: datetime,
) -> str:
    """Render one self-contained HTML report.

    A section is {heading, kind, rows, label_key, value_key, note} where kind is
    "bars" or "table". Keeping the shape this narrow means a caller cannot
    smuggle unescaped HTML in through a section.
    """
    blocks: list[str] = []
    for section in sections:
        heading = _escape(section.get("heading") or "")
        note = section.get("note")
        rows = list(section.get("rows") or [])[:MAX_REPORT_ROWS]
        kind = section.get("kind") or "table"
        label_key = section.get("label_key")
        value_key = section.get("value_key")

        blocks.append(f'<section class="card"><h2>{heading}</h2>')
        if note:
            blocks.append(f'<p class="note">{_escape(note)}</p>')

        if kind == "bars" and label_key and value_key and rows:
            blocks.append(_bars(rows, label_key, value_key))
        elif kind == "trend" and value_key and rows:
            blocks.append(_sparkline([float(row[value_key]) for row in rows]))

        if rows:
            keys = list(rows[0].keys())
            blocks.append('<table><thead><tr>')
            blocks.extend(f"<th>{_escape(key)}</th>" for key in keys)
            blocks.append("</tr></thead><tbody>")
            for row in rows:
                blocks.append("<tr>")
                blocks.extend(f"<td>{_escape(row.get(key, ''))}</td>" for key in keys)
                blocks.append("</tr>")
            blocks.append("</tbody></table>")
        elif kind != "bars":
            blocks.append('<p class="empty">داده‌ای برای نمایش نیست.</p>')
        blocks.append("</section>")

    stamp = generated_at.strftime("%Y-%m-%d %H:%M")
    # %-mapping, not str.format or an f-string: this template is CSS and HTML,
    # so every brace is literal, and .format would require doubling all of them.
    # %(name)s leaves the braces alone. The one suppression is on the line above
    # the template for exactly that reason.
    return _REPORT_TEMPLATE % {  # noqa: UP031
        "title": _escape(title),
        "org": _escape(organization_name),
        "stamp": _escape(stamp),
        "blocks": "".join(blocks),
        **PALETTE,
    }


_REPORT_TEMPLATE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
/* One self-contained file: the palette is inlined because the product's
   stylesheet is not shipped next to a downloaded report. */
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 24px;
  background: %(canvas)s; color: %(ink)s;
  font-family: Vazirmatn, "Segoe UI", Tahoma, sans-serif;
  line-height: 1.7;
}
main { max-width: 900px; margin: 0 auto; display: grid; gap: 20px; }
header { border-bottom: 1px solid %(hairline)s; padding-bottom: 20px; }
h1 { font-size: 28px; font-weight: 400; margin: 0 0 6px; }
h2 { font-size: 17px; font-weight: 600; margin: 0 0 4px; }
.meta { color: %(muted)s; font-size: 13px; }
.card {
  background: %(card)s; border: 1px solid %(hairline)s;
  border-radius: 12px; padding: 20px;
}
.note { color: %(body)s; font-size: 13px; margin: 0 0 14px; }
.empty { color: %(muted)s; font-size: 13px; }
table { width: 100%%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
th {
  text-align: right; font-weight: 600; color: %(body)s;
  border-bottom: 1px solid %(hairline)s; padding: 8px 10px;
}
td { border-bottom: 1px solid %(hairline_soft)s; padding: 8px 10px; vertical-align: top; }
tr:last-child td { border-bottom: 0; }
svg text { font-family: Vazirmatn, "Segoe UI", Tahoma, sans-serif; }
footer { color: %(muted)s; font-size: 12px; text-align: center; padding-top: 8px; }
</style>
</head>
<body>
<main>
  <header>
    <h1>%(title)s</h1>
    <p class="meta">%(org)s — ساخته‌شده در %(stamp)s</p>
  </header>
  %(blocks)s
  <footer>این گزارش به‌صورت خودکار توسط هوش سازمان تولید شده است.</footer>
</main>
</body>
</html>
"""


def render_csv_report(sections: list[dict]) -> str:
    """The first tabular section, as CSV.

    One table per file: a CSV with several unrelated tables stacked in it is not
    parseable, and the operator who wants the second one can request it.
    """
    for section in sections:
        rows = list(section.get("rows") or [])
        if rows:
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows[:MAX_REPORT_ROWS]:
                writer.writerow({key: row.get(key, "") for key in rows[0].keys()})
            return buffer.getvalue()
    return ""


async def save_report(
    session: AsyncSession,
    *,
    organization: Organization,
    title: str,
    content: str,
    extension: str,
    user_id=None,
    detail: dict | None = None,
) -> KnowledgeAsset:
    """Write a generated report to disk and register it as an asset.

    It becomes an ordinary KnowledgeAsset in status 'ready': the file is already
    complete, so there is nothing for the processing pipeline to do, and routing
    it through the queue would make it appear in the user's files minutes later
    with no explanation. Quota is charged the same way an upload is, because the
    bytes are just as real.
    """
    from backend.knowledge.assets import _assert_quota, _storage_dir

    encoded = content.encode("utf-8")
    await _assert_quota(session, organization, len(encoded))

    safe_stem = "".join(
        character for character in title if character.isalnum() or character in " -_"
    ).strip()[:80]
    filename = (safe_stem or "report") + "-" + uuid.uuid4().hex[:8] + "." + extension

    directory = _storage_dir(organization.id)
    target = Path(directory) / filename

    # The path is built from a sanitized stem plus a uuid, never from raw title
    # text, so a title containing ../ cannot escape the organization directory.
    if target.parent.resolve() != Path(directory).resolve():
        raise ApiError(400, "REPORT_PATH_INVALID", "The report path is not allowed.")

    target.write_bytes(encoded)

    asset = KnowledgeAsset(
        organization_id=organization.id,
        name=filename,
        storage_path=str(target),
        size_bytes=len(encoded),
        extension=extension,
        status="ready",
        uploaded_by=user_id,
        asset_type="text",
        classified_at=_utc_now(),
    )
    session.add(asset)
    await session.flush()

    await record_audit(
        session,
        "report.generated",
        organization_id=organization.id,
        actor_user_id=user_id,
        entity_type="knowledge_asset",
        entity_id=asset.id,
        detail={"title": title, "extension": extension, **(detail or {})},
    )
    return asset
