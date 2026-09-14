"""Chart tool: the agent returns a real chart file, not a description of one.

The PO asked for "ابزارهای مصورسازی" - visualization tools the agent can reach
for when a user asks for a report. This is the chart half; build_report is the
document half.

WHY A FILE AND NOT AN INLINE IMAGE. The frontend already has an inline-SVG chart
kit (frontend/src/components/ui/chart.tsx) for charts the app draws from data it
already has. That path cannot serve this one: the agent's chart must survive
outside the session, be downloadable, be attachable, and be visible next to the
user's other files. So it is rendered server-side into a self-contained HTML
document and registered as a KnowledgeAsset - the same lifecycle as a report.

WHY HAND-WRITTEN SVG HERE TOO. No charting library is in the dependency set, and
the catalogs confirmed none should be added (they contain no chart-generation
tool at all - verified by searching both files for chart/plot/matplotlib/echarts/
d3/pptx/xlsx/report-generation terms). Hand-written SVG also means the output
inherits the design tokens exactly, with no library theme to fight.

Full hex values, not var(): a downloaded file has no stylesheet next to it. Same
reasoning as reporting.py, and the palette is imported from there so the two can
never diverge.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.agent.tools.registry import ToolContext, ToolResult, ToolSpec, register

# Reused from the report renderer so a chart and a report in the same session
# cannot disagree about what "the accent colour" is. Imported at module level,
# with the rest, rather than beside its first use: a function-local import here
# would hide a circular-import problem until the tool was first called.
from backend.knowledge.reporting import MONO_STACK, PALETTE
from backend.models import Organization

MAX_POINTS = 200
CHART_TYPES = ("bar", "line", "donut", "table")

_SERIES_COLOURS = (
    PALETTE["accent_active"],
    PALETTE["success"],
    PALETTE["sky"],
    PALETTE["violet"],
    PALETTE["amber"],
    PALETTE["peach"],
)


def _esc(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _fmt(value) -> str:
    """Persian-friendly number formatting: no scientific notation, no trailing
    .0, and thousands separators so a revenue figure is readable."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return _esc(value)


def _bar_svg(points: list[dict], label_key: str, value_key: str) -> str:
    """Horizontal bars. Persian labels do not fit under vertical bars without
    rotation, so horizontal is the only readable orientation in RTL."""
    values = [float(point[value_key]) for point in points]
    top = max(values) if values else 1.0
    top = top or 1.0
    row_height = 30
    height = row_height * len(points) + 24
    bars: list[str] = []
    for index, point in enumerate(points):
        value = float(point[value_key])
        width = max(2.0, (value / top) * 420.0)
        y = index * row_height + 12
        bars.append(
            f'<text x="620" y="{y + 13}" text-anchor="end" '
            f'font-family="{MONO_STACK}" font-size="12" fill="{PALETTE["body"]}">'
            f"{_esc(point[label_key])}</text>"
        )
        bars.append(
            f'<rect x="196" y="{y}" width="416" height="16" rx="4" '
            f'fill="{PALETTE["hairline_soft"]}"/>'
        )
        bars.append(
            f'<rect x="196" y="{y}" width="{width:.1f}" height="16" rx="4" '
            f'fill="{PALETTE["accent_active"]}"/>'
        )
        bars.append(
            f'<text x="188" y="{y + 13}" text-anchor="end" '
            f'font-family="{MONO_STACK}" font-size="12" fill="{PALETTE["ink"]}">'
            f"{_fmt(value)}</text>"
        )
    return (
        f'<svg viewBox="0 0 640 {height}" width="100%" height="{height}" '
        f'role="img" aria-label="نمودار میله‌ای">' + "".join(bars) + "</svg>"
    )


def _line_svg(points: list[dict], label_key: str, value_key: str) -> str:
    values = [float(point[value_key]) for point in points]
    top = max(values) if values else 1.0
    bottom = min(values) if values else 0.0
    span = (top - bottom) or 1.0
    width, height, pad = 640.0, 220.0, 30.0
    usable = width - pad * 2

    coords: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = pad + (index / max(1, len(values) - 1)) * usable
        y = height - pad - ((value - bottom) / span) * (height - pad * 2)
        coords.append((x, y))

    path = " ".join(
        ("M" if index == 0 else "L") + f"{x:.1f} {y:.1f}" for index, (x, y) in enumerate(coords)
    )
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{PALETTE["accent_active"]}"/>'
        for x, y in coords
    )
    first = _esc(points[0][label_key]) if points else ""
    last = _esc(points[-1][label_key]) if points else ""
    return (
        f'<svg viewBox="0 0 {int(width)} {int(height)}" width="100%" height="{int(height)}" '
        f'role="img" aria-label="نمودار روند">'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" '
        f'stroke="{PALETTE["hairline"]}" stroke-width="1"/>'
        f'<path d="{path}" fill="none" stroke="{PALETTE["accent_active"]}" stroke-width="2"/>'
        f"{dots}"
        f'<text x="{pad}" y="{height - 8}" font-size="11" fill="{PALETTE["muted"]}">{first}</text>'
        f'<text x="{width - pad}" y="{height - 8}" text-anchor="end" font-size="11" '
        f'fill="{PALETTE["muted"]}">{last}</text>'
        f"</svg>"
    )


def _donut_svg(points: list[dict], label_key: str, value_key: str) -> str:
    values = [max(0.0, float(point[value_key])) for point in points]
    total = sum(values) or 1.0
    radius, circumference = 70.0, 2 * 3.14159265 * 70.0
    arcs: list[str] = []
    legend: list[str] = []
    start = 0.0
    for index, point in enumerate(points):
        dash = (values[index] / total) * circumference
        colour = _SERIES_COLOURS[index % len(_SERIES_COLOURS)]
        arcs.append(
            f'<circle cx="95" cy="95" r="{radius}" fill="none" stroke="{colour}" '
            f'stroke-width="22" stroke-dasharray="{dash:.1f} {circumference - dash:.1f}" '
            f'stroke-dashoffset="{-start:.1f}" transform="rotate(-90 95 95)"/>'
        )
        start += dash
        percent = (values[index] / total) * 100
        legend.append(
            f'<li><span style="display:inline-block;width:9px;height:9px;border-radius:2px;'
            f'background:{colour};margin-inline-end:6px"></span>'
            f"{_esc(point[label_key])} — {_fmt(values[index])} ({percent:.0f}٪)</li>"
        )
    return (
        '<div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">'
        '<svg viewBox="0 0 190 190" width="190" height="190" role="img" '
        'aria-label="نمودار دونات">'
        + "".join(arcs)
        + "</svg>"
        + '<ul style="list-style:none;padding:0;margin:0;font-size:13px;line-height:1.9">'
        + "".join(legend)
        + "</ul></div>"
    )


def _table_html(points: list[dict]) -> str:
    if not points:
        return "<p>داده‌ای نیست.</p>"
    keys: list[str] = []
    for point in points:
        for key in point:
            if key not in keys:
                keys.append(key)
    head = "".join(f"<th>{_esc(key)}</th>" for key in keys)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(point.get(key, ''))}</td>" for key in keys) + "</tr>"
        for point in points
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _document(title: str, organization_name: str, body: str, generated_at: datetime) -> str:
    """One self-contained HTML file: no external CSS, no script, no fonts fetched."""
    stamp = generated_at.strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; padding:40px 24px; background:{PALETTE["canvas"]};
         color:{PALETTE["ink"]}; font-family:Vazirmatn,Tahoma,system-ui,sans-serif;
         font-size:14px; line-height:1.8; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  h1 {{ font-size:24px; font-weight:600; margin:0 0 4px; }}
  .meta {{ color:{PALETTE["muted"]}; font-size:12px; font-family:{MONO_STACK};
          margin-bottom:24px; }}
  .card {{ background:{PALETTE["card"]}; border:1px solid {PALETTE["hairline"]};
          border-radius:12px; padding:20px; margin-bottom:16px; }}
  h2 {{ font-size:15px; font-weight:600; margin:0 0 12px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:right; padding:8px 10px; border-bottom:1px solid {PALETTE["hairline_soft"]}; }}
  th {{ color:{PALETTE["body"]}; font-weight:500; }}
  td {{ font-family:{MONO_STACK}; }}
  footer {{ color:{PALETTE["muted"]}; font-size:11px; text-align:center; margin-top:28px; }}
</style>
</head>
<body><div class="wrap">
<h1>{_esc(title)}</h1>
<div class="meta">{_esc(organization_name)} · {stamp}</div>
{body}
<footer>ساخته‌شده توسط HiveOS</footer>
</div></body></html>
"""


async def _run(ctx: ToolContext, arguments: dict) -> ToolResult:
    from backend.knowledge.reporting import save_report

    title = str(arguments.get("title") or "").strip()
    if not title:
        return ToolResult(content="عنوان نمودار لازم است.", ok=False)

    points = arguments.get("data")
    if not isinstance(points, list) or not points:
        return ToolResult(content="برای نمودار باید data با حداقل یک ردیف بفرستی.", ok=False)
    points = [point for point in points if isinstance(point, dict)][:MAX_POINTS]
    if not points:
        return ToolResult(content="data شامل ردیف معتبر نبود.", ok=False)

    chart_type = str(arguments.get("chart_type") or "bar").lower()
    if chart_type not in CHART_TYPES:
        chart_type = "bar"
    label_key = str(arguments.get("label_key") or "").strip()
    value_key = str(arguments.get("value_key") or "").strip()

    if chart_type != "table":
        if not label_key or not value_key:
            return ToolResult(
                content="برای نمودار باید label_key و value_key را بدهی.", ok=False
            )
        missing = [
            key
            for key in (label_key, value_key)
            if any(key not in point for point in points[:1])
        ]
        if missing:
            available = ", ".join(str(key) for key in points[0])
            return ToolResult(
                content=f"کلید {missing[0]} در data نبود. کلیدهای موجود: {available}",
                ok=False,
            )

    if chart_type == "bar":
        body = _bar_svg(points, label_key, value_key)
    elif chart_type == "line":
        body = _line_svg(points, label_key, value_key)
    elif chart_type == "donut":
        # Six arcs is where a donut stops being readable; the rest becomes a
        # single "other" row rather than an unreadable ring of slivers.
        if len(points) > 6:
            head, tail = points[:5], points[5:]
            other = sum(float(point[value_key]) for point in tail)
            points = head + [{label_key: "سایر", value_key: other}]
        body = _donut_svg(points, label_key, value_key)
    else:
        body = _table_html(points)

    organization = await ctx.session.get(Organization, ctx.organization_id)
    if organization is None:
        return ToolResult(content="سازمان یافت نشد.", ok=False)

    document = _document(title, organization.name, f'<div class="card">{body}</div>', datetime.now(UTC))
    asset = await save_report(
        ctx.session,
        organization=organization,
        title=title,
        content=document,
        extension="html",
        user_id=ctx.user_id,
        detail={"source": "agent_chart_tool", "chart_type": chart_type,
                "execution_id": str(ctx.execution_id or "")},
    )
    return ToolResult(
        content=(
            f"نمودار «{title}» ({chart_type}) با {len(points)} داده ساخته و ذخیره شد "
            f"(نام فایل: {asset.name}). خودِ نمودار را در پاسخ تکرار نکن؛ "
            "فقط بگو ساخته شد و چه چیزی را نشان می‌دهد."
        ),
        ok=True,
        meta={"asset_id": str(asset.id), "filename": asset.name, "chart_type": chart_type},
    )


SPEC = ToolSpec(
    name="build_chart",
    description=(
        "ساخت نمودار قابل دانلود از داده و ذخیرهٔ آن در فایل‌های کاربر. "
        "کِی صدا بزن: وقتی کاربر می‌خواهد داده را بصری ببیند — مقایسه، روند، "
        "سهم هر بخش، یا «نمودار بکش/نشان بده». "
        "chart_type یکی از: bar (مقایسه)، line (روند زمانی)، donut (سهم از کل)، "
        "table (جدول خام). برای bar/line/donut باید label_key و value_key بدهی و "
        "هر ردیف data باید آن کلیدها را داشته باشد. "
        "خروجی: نام فایل ذخیره‌شده."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "عنوان نمودار، فارسی و کوتاه."},
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "donut", "table"],
                "description": "پیش‌فرض bar.",
            },
            "data": {
                "type": "array",
                "description": "ردیف‌های داده، هر ردیف یک شیء کلید-مقدار.",
                "items": {"type": "object"},
            },
            "label_key": {"type": "string", "description": "کلید برچسب در هر ردیف."},
            "value_key": {"type": "string", "description": "کلید مقدار عددی در هر ردیف."},
        },
        "required": ["title", "data"],
    },
    handler=_run,
    writes=True,
)

register(SPEC)
