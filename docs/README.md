# docs/ — فهرست مستندات کد‌محور HiveOS

این پوشه بخشی از monorepo است که طبق ADR-002 محل قرارداد کد و تصمیمات repo-local
است. **ADRها / Engineering Standards / Architecture کانونی در
`Dropbox/Hive/doc/` (CEO-governed) نگهداری می‌شوند** و اینجا تکرار نمی‌شوند
(رکورد تصمیم: `decisions/2026-08-20-docs-contract-alignment.md`).

## محتوا

| مسیر | نقش |
|---|---|
| `openapi.yaml` | **SSoT قرارداد API** (OpenAPI 3.1) — توافق یکتای backend / frontend / QA برای Epic-01. نسخه‌ی ردیابی‌شده: `0.2.0` (هم‌راستا با `backend/app/config.py → app_version`). |
| `decisions/` | تصمیم‌های repo-local (فرآیند سبک ADR-019 decision 6) — مثل پاکت صفحه‌بندی `{items, meta}` (S1-18). |
| `README.md` | همین فایل. |

## رابطه با SSoT

- **قرارداد کد (openapi.yaml)** یکتاست و با پیاده‌سازی backend (`app/schemas.py`)
  تراز ۱:۱ نگه داشته می‌شود (`tests/test_contract.py` آن را گارد می‌کند).
- **اسناد حاکمیتی** (ADR-002..021, Standards, Architecture, Terminology, Design
  System) در Dropbox/doc/ نسخه‌برداری و توسط CEO نگهداری می‌شوند. این پوشه آن‌ها را
  بازنشر نمی‌کند؛ فقط ارجاع می‌دهد تا از واگرایی (SSoT تکراری) جلوگیری شود.

## Decision points (باز، برای PO/CEO)

1. **BYOK / `apiKey` در برابر ADR-020** — `AIModelConfiguration.apiKey` هم در کد هم
   در قرارداد هنوز هست؛ ADR-020 (accepted) BYOK را حذف و مدل مدیریت‌شده + کیف پول
   اعتباری را جایگزین کرده، اما مهاجرت کد (روتر/metering/billing) انجام نشده. حذف
   `apiKey` نیازمند change در backend (خارج از اسکوپ docs) و تصمیم CEO است.
   جزئیات: `decisions/2026-08-20-docs-contract-alignment.md`.
2. **محل SSoT (repo `docs/` در برابر Dropbox `doc/`)** — ADR-002 می‌گوید `docs/`
   «تنها منبع رسمی مستندات پروژه» است، اما ADRهای کانونی عملاً در Dropbox زندگی
   می‌کنند. تصمیم نهایی درباره‌ی مکانیسم یکسان‌سازی (mirror/لینک/کوچ کامل) با CEO است.
