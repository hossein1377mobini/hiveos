# HiveOS

پلتفرم «کارمند دیجیتال» / سازمان‌آمیز (Organizational Intelligence Platform) — v0.1 (**Hive Mind**).

اسکلت monorepo طبق **ADR-002** (Repository Structure). قرارداد API (SSoT کد) در `docs/openapi.yaml`؛ ADRها/Standards/Architecture کانونی (CEO-governed) در `Dropbox/Hive/doc/` نگهداری می‌شوند.

## ساختار

```
hiveos/
├── docs/             # قرارداد API (openapi.yaml) + تصمیمات repo-local (decisions/)
│                     #   (ADR/Standards/Architecture کانونی در Dropbox/Hive/doc — CEO-governed)
├── frontend/app/     # رابط کاربری (React + TypeScript + Vite) — فقط UX/ارتباط با Backend
├── backend/          # thin API (Python/FastAPI، SQLAlchemy-2 async، asyncpg، pgvector) — v0.1
├── ai/               # موتور هوش مصنوعی (Agentها، LLM، RAG) — فاز بعد (خالی)
├── infrastructure/   # Docker/Compose، initdb (pgvector)، CI/CD
├── scripts/          # اسکریپت‌های کمکی (Build، Migration، Utilities)
└── README.md
```

## موقعیت فعلی (وضعیت 2026-08-19)

- **Epic-01 کامل و تحویل‌شده:** backend (US-001..008) + frontend (wizard React ۷ مرحله‌ای RTL) — merged روی `main`.
- **استک v0.1 (ADR-019/021):** thin API = Python/FastAPI؛ Vector Store = **pgvector**؛ Embedding = **fastembed محلی** (بدون هزینه‌ی ابر)؛ OTP = **Mock** (کد در لاگ uvicorn)؛ Auth = کوکیِ HttpOnly+Secure؛ Migrations = **Alembic** (prod) / `create_all` (dev).
- گیتوی .NET فاز ۲؛ رانتایم Agent/RAG در `ai/` — در اپیک‌های بعدی.

## 🚀 اجرا (Getting Started)

پیش‌نیاز: **Python 3.11+** · **uv** · **Node 18+** · **Docker**.

### ۱. زیرساخت (دیتابیس + redis) — یک بار
```bash
docker compose -f infrastructure/docker-compose.yml up -d
```
Postgres+pgvector → `localhost:5434` (db: `hiveos`)، Redis → `localhost:6380`. (جداست از Kaneo؛ پورت‌ها ۵۴۳۴/۶۳۸۰.)

### ۲. بکاند (`localhost:8100`)
```bash
cd backend
cp .env.example .env        # پیکربندی dev (کافیست؛ کپی شود)
uv sync                     # نصب وابستگی‌ها در .venv
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8100   # ویندوز
# (macOS/Linux: ./.venv/bin/python)
```
- جدول‌ها خودکار در boot ساخته می‌شوند (در dev با `create_all`؛ خارج از dev با `alembic upgrade head`).
- `Windows/PowerShell`: `$env:PYTHONPATH=""` را قبل از دستور uvicorn بگذارید.

### ۳. فرانت‌اند (`http://localhost:5199`)
```bash
cd frontend/app
npm install
npm run dev
```
باز کنید: **`http://localhost:5199`** — Vite `/api` را به `localhost:8100` پروکسی می‌کند (کوکی same-origin؛ بدون CORS در dev).

تست سلامت اتصال هر دو سرور:
```bash
curl http://localhost:5199/api/v1/healthz   # → {"status":"ok"}
```

### 🧪 فلو و تست
- **فلو:** ساخت سازمان → مدیر → تأیید کد → فضای کار → هوش سازمان → اسناد → تمام.
  کد OTP با **MockSms** تولید می‌شود؛ آن را در **لاگ uvicorn** (جستجوی `MOCK-SMS` یا عدد ۶ رقمی) پیدا کنید.
- در مراحل «هوش سازمان/اسناد» اولین بار مدل embedding محلی (fastembed ~۲GB) دانلود/کش می‌شود.
- **تست اتوماتیک:**
  - فرانت: `cd frontend/app && npm run test` (Vitest ۲۸ مورد) · `npm run build`
  - بک‌اند: `cd backend && PYTHONPATH= ./.venv/Scripts/python.exe -m pytest -q` (۸۹ مورد، پوشش ≥۸۵٪ — فعلاً ۸۹٪)

## قوانین ساختار (ADR-002)

1. هیچ فایل مستندی خارج از `docs/` قرار نگیرد.
2. هیچ کد AI داخل `backend/` قرار نگیرد.
3. هیچ Business Logic داخل `frontend/` قرار نگیرد.
4. هر بخش فقط مسئولیت خودش را دارد.
