"""Report tool: the agent composes a report and it lands in the user's files.

Why this is a tool and not a page action: the PO's requirement is that a user
*asks for a report* in conversation and it happens - "برای وقت‌هایی که کاربر
درخواست گزارش می‌کنه". A button on a page can only ever produce the report the
button's author anticipated. A tool lets the model decide the sections from the
question it was actually asked.

The heavy lifting already existed in backend.knowledge.reporting (render_html_report
/ render_csv_report / save_report, written earlier this session). This module is
the agent-facing contract around it: validate what the model produced, render,
persist, and return something short enough to put back in the context window.

The returned content deliberately does NOT include the report body. A 40-row
table echoed back into the conversation would cost more context than the answer
and the user already has the file.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.agent.tools.registry import ToolContext, ToolResult, ToolSpec, register
from backend.models import Organization

MAX_SECTIONS = 12
MAX_ROWS_PER_SECTION = 500
VALID_FORMATS = ("html", "csv")


async def _run(ctx: ToolContext, arguments: dict) -> ToolResult:
    from backend.knowledge.reporting import render_csv_report, render_html_report, save_report

    title = str(arguments.get("title") or "").strip()
    if not title:
        return ToolResult(content="عنوان گزارش لازم است. دوباره با title فراخوانی کن.", ok=False)

    sections = arguments.get("sections")
    if not isinstance(sections, list) or not sections:
        return ToolResult(
            content="گزارش بدون بخش معنا ندارد. sections را با حداقل یک بخش بفرست.", ok=False
        )
    if len(sections) > MAX_SECTIONS:
        sections = sections[:MAX_SECTIONS]

    # Normalise before rendering so reporting.py receives the exact shape it
    # validates against, rather than trusting whatever the model emitted.
    clean: list[dict] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        rows = section.get("rows")
        clean.append(
            {
                "heading": str(section.get("heading") or "").strip(),
                "kind": section.get("kind") if section.get("kind") in ("bars", "trend", "table") else "table",
                "rows": rows[:MAX_ROWS_PER_SECTION] if isinstance(rows, list) else [],
                "label_key": section.get("label_key"),
                "value_key": section.get("value_key"),
                "note": section.get("note"),
            }
        )
    if not clean:
        return ToolResult(content="هیچ بخش معتبری در sections نبود.", ok=False)

    report_format = str(arguments.get("format") or "html").lower()
    if report_format not in VALID_FORMATS:
        report_format = "html"

    organization = await ctx.session.get(Organization, ctx.organization_id)
    if organization is None:
        return ToolResult(content="سازمان یافت نشد.", ok=False)

    generated_at = datetime.now(UTC)
    if report_format == "csv":
        content = render_csv_report(clean)
        extension = "csv"
    else:
        content = render_html_report(
            title=title,
            organization_name=organization.name,
            sections=clean,
            generated_at=generated_at,
        )
        extension = "html"

    if not content.strip():
        return ToolResult(content="گزارش خالی تولید شد؛ دادهای برای درج نبود.", ok=False)

    asset = await save_report(
        ctx.session,
        organization=organization,
        title=title,
        content=content,
        extension=extension,
        user_id=ctx.user_id,
        detail={"source": "agent_tool", "execution_id": str(ctx.execution_id or "")},
    )

    row_counts = [len(section["rows"]) for section in clean]
    return ToolResult(
        content=(
            f"گزارش «{title}» ساخته شد و در فایل‌های کاربر ذخیره شد "
            f"(نام فایل: {asset.name}، قالب: {extension}، "
            f"{len(clean)} بخش، مجموع {sum(row_counts)} ردیف). "
            "محتوای گزارش را در پاسخ تکرار نکن؛ فقط بگو ساخته شد و چه بخش‌هایی دارد."
        ),
        ok=True,
        meta={"asset_id": str(asset.id), "filename": asset.name, "sections": len(clean)},
    )


SPEC = ToolSpec(
    name="build_report",
    description=(
        "ساخت گزارش قابل دانلود (HTML یا CSV) از داده‌ای که در گفتگو به دست آمده و "
        "ذخیرهٔ آن در فایل‌های کاربر. "
        "کِی صدا بزن: وقتی کاربر صریحاً گزارش، جمع‌بندی رسمی، فایل خروجی یا "
        "«گزارش بساز/بده» می‌خواهد. برای پاسخ معمولی صدا نزن. "
        "هر بخش شامل heading، kind (bars برای مقایسهٔ میله‌ای، trend برای روند، "
        "table برای جدول)، rows (آرایه‌ای از شیءهای کلید-مقدار)، و برای bars/trend "
        "باید label_key و value_key هم بدهی. "
        "خروجی: نام فایل ذخیره‌شده. محتوای گزارش را در پاسخ تکرار نکن."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "عنوان گزارش، فارسی و کوتاه."},
            "format": {
                "type": "string",
                "enum": ["html", "csv"],
                "description": "پیش‌فرض html. csv را وقتی بخواه که کاربر جدول خام می‌خواهد.",
            },
            "sections": {
                "type": "array",
                "description": "بخش‌های گزارش، حداکثر ۱۲ بخش.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "kind": {"type": "string", "enum": ["bars", "trend", "table"]},
                        "rows": {"type": "array", "items": {"type": "object"}},
                        "label_key": {"type": "string"},
                        "value_key": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["heading", "rows"],
                },
            },
        },
        "required": ["title", "sections"],
    },
    handler=_run,
    writes=True,
)

register(SPEC)
