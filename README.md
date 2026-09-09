# HiveOS — کد v0.1

مونوریپوی کد HiveOS. مستندات در ریپوی `hive/` می‌ماند — مرجع اجرا: `hive/documentation/development-workflow.md` §۸ (تسک‌های S0..S5).

## ساختار (ADR-002)

| مسیر | نقش |
|------|-----|
| `backend/` | API و Business Logic — FastAPI (ADR-021) |
| `frontend/` | React + TypeScript (Vite) — از T-S0-5 |
| `ai/` | AI Engine (RAG / Agent Runtime) — از S2/S3 |
| `infrastructure/` | Compose / Deploy — از T-S0-3/T-S0-4 |
| `scripts/` | اسکریپت‌های کمکی |

## قواعد

- Python 3.11 با uv (`.python-version`)
- هیچ secret در گیت (ADR-022) — کانفیگ از پنل ادمین / env
- هر تسک روی شاخه `task/T-Sn-n-slug`؛ merge به main فقط با تأیید PO
- چک محلی: `cd backend && uv run ruff check . && uv run pytest`
