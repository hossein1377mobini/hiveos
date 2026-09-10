# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-10 (T-S0-5 تأیید و merge شد — main = `f1cfe19`؛ deploy staging منتظر روشن‌شدن سرور)

## شروع سشن جدید از اینجا — تسک بعدی: **T-S1-1** (مدل داده سازمان/Owner + migration، US-001/002)

1. **S0 کامل و بسته شد** — آخرین merge: T-S0-5 پایه فرانت → main = `f1cfe19` (PR #3، ریویو نوبت ۱ اعمال، گزارش: `hive/reports/tasks/2026-09-10-T-S0-5.md`). شاخه حذف شد.
2. **اقدام معلق PO (بلاکر deploy، نه کد):** سرور staging خاموش است (22/80 بسته — پروب 2026-09-10) → deploy خودکار در scp timeout (runs 34456622920 / 34459406014). بعد از روشن‌کردن سرور: `gh run rerun 34456622920 --failed` (با PAT فعلی gh ممکن است) یا push بعدی به main.
3. **آماده‌سازی T-S1-1 (به ترتیب):**
   - شاخه: `task/T-S1-1-org-model` از `main`.
   - بخوان: `hive/epics/epic-01/us-001-register-a-new-organization.md` + `us-002-create-organization-owner-account.md` (AC مبنای تست) + `hive/epics/epic-01/epic-01-overview.md` + DoD + coding standards؛ برای واژگان UI/Copy: `hive/product/terminology.md` §۷.
   - خروجی هدف (§۸ development-workflow): مدل ORM سازمان/Workspace/Owner + migration Alembic (`0002_...`، قابل بازگشت/downgrade) + تست‌ها (واحد + AC) — **API ثبت‌نام تسک جدا است (T-S1-2)**، اینجا فقط مدل داده + migration.
   - الگوی migration از `backend/migrations/versions/0001_baseline.py`؛ downgrade را جدی پیاده کن (الزام rollback-migration از S0).
   - تست: از `backend/` → `..\backend\.venv\Scripts\python.exe -m pytest -q` و ruff؛ DB dev روی 5434 (compose).
   - گزارش: `hive/reports/tasks/2026-09-10-T-S1-1.md` طبق قالب §۴ → ریویو PO → merge فقط با تأیید.
4. نکات فرانت از T-S0-5 (برای T-S1-9 مفید): shadcn semantic aliases در `frontend/src/styles.css` آماده‌اند؛ سؤال باز «سرو فرانت روی staging» (پیشنهاد T-S0-6) هنوز بی‌تصمیم است.

## وضعیت S0 — کامل و بسته (2026-09-10)

| تسک | وضعیت | شواهد |
|-----|-------|-------|
| T-S0-1 اسکلت+CI | merge شده؛ ریویو نوبت ۱ اعمال؛ R1-1 بسته (CI run سبز) | PR #2، runs 34411938557/34412023587 |
| T-S0-2 FastAPI | merge شده؛ ریویو نوبت ۱+۲ اعمال (version از metadata، CORS validator، DB_URL fail-fast؛ 15 tests) | کامیت‌های c1274a9/9ba45ea |
| T-S0-3 Compose+Alembic | merge شده؛ ریویو نوبت ۱ اعمال (secrets از env، حذف prod overlay، sync-url helper)؛ E2E سبز | کامیت bf843c0 |
| T-S0-4 Deploy pipeline | merge شده؛ ریویو نوبت ۱+۲ اعمال (root guard، تک workflow، .dockerignore با اثبات NO-LEAK، USER 10001 non-root)؛ **deploy خودکار سبز** | run 34416119083 — staging روی `ci-149cf43...` |
| یکپارچه‌سازی | PR #2 merge شد → main = `cebf0e0`؛ CI backend روی main سبز (run 34415142318) | — |
| T-S0-5 پایه فرانت | merge شده (تأیید PO)؛ ریویو نوبت ۱ اعمال — بلاکر R5-1 «fail-fast DATABASE_URL بی‌اثر بود» بسته شد + ۴ تست (19 passed)؛ فرانت: Vite7/React19/TS strict/Tailwind4، AppShell RTL، توکن‌ها، پروکسی dev، vitest 2/2 | PR #3، runs 34422508567/34455274256/34455681355؛ main = `f1cfe19` |

باز فنی S0: فقط rollback-migration (الزام S2 قبل از اولین migration مخرب — در README ثبت).

## زیرساخت و دسترسی (2026-09-10)

- سرورها: staging 193.93.169.136 / prod 193.93.169.204 — SSH با کلید `C:\Users\Hossein Mobini\.ssh\hiveos_key` + میان‌برهای config `hiveos-staging`/`hiveos-prod`. PO سرورها را خاموش نگه می‌دارد؛ فقط حین push به main لازم‌اند.
- استک staging: db (project `hiveos`) + api (project `hiveos-app`، external network `hiveos_default`)؛ nginx میزبان :80 → 127.0.0.1:8100؛ `.previous-tag` = `ci-149cf43...`.
- Deploy path: push main → CI (backend job) → build image `hiveos/api:ci-<sha>` → save/scp/load → `remote-deploy.sh` (env از secret سرور، alembic، healthcheck :8100+:80، rollback خودکار). تنها workflow: `ci-deploy.yml`.
- Secrets ریپو (ست شده): `STAGING_HOST`، `STAGING_SSH_KEY`.
- GitHub: push/PR/secrets با credential manager سیستم کار می‌کند. rerun-failed-jobs و workflow-file push با PAT فعلی محدودیت دارد → trigger deploy با push به main.

## بازهای غیرفنی (PO)

1. **پنل فردوسی:** باز کردن 80/443 برای هر دو سرور — بسته‌شدن لایه‌ی ارائه‌دهنده است (اثبات: کانتر ufw صفر روی 80/443 در حالی که 22 می‌شمارد؛ nginx listen دارد). تا باز نشود HTTPS عمومی (مسیر Arvan) کار نمی‌کند؛ deploy مستقل از آن است.
2. **PAT قدیمی:** فایل transfer حذف شد؛ PAT قبلی هنوز معتبر است (در credential manager). PO در GitHub → Settings → Developer settings → PAT آن را revoke کند و در صورت نیاز توکن جدید با دسترسی‌های Contents+Actions+Pull requests+Workflow بسازد.
3. `agent.md` §0 به‌روز شد (با اجازه PO در همین سشن).
4. شاخه‌های کار S0 روی GitHub حذف شدند (merge شده‌اند؛ تاریخچه در main حفظ است).

## دستورهای ایستاده PO

1. مبنای کار = اسناد فنی `hive/` — خارج از ADR/scope/decided چیزی از خود نساز؛ ابهام = سؤال.
2. ریویو نوبتی: گزارش‌ها در `hive/reports/tasks/`؛ PO/ریویوئر نظرات را داخل خود فایل گزارش می‌نویسد؛ عامل اعمال می‌کند و «اعمال نظرات» ثبت می‌کند.
3. merge فقط با تأیید صریح PO؛ main همیشه deployable.
4. هیچ secret در گیت (ADR-022)؛ کلیدها نزد PO.
5. native postgres ویندوزی روی 5432 مال PO است — دست نزن؛ DB اپ dev روی 5434.

## نکات فنی ماندگار

- CORS: `CORS_ORIGINS` env کاما-جدا؛ خالی = deny؛ `*` فقط dev (validator رد می‌کند در staging/prod). `DATABASE_URL` در staging/prod الزامی (fail-fast).
- تصویر api: non-root uid 10001؛ `.dockerignore` ریشه‌ای — دست نزن مگر با اثبات.
- rollback فقط image — قبل از اولین migration مخرب در S2 گام schema لازم دارد.
- local dev: `infrastructure/.env` (gitignored) + `docker compose -f infrastructure/docker-compose.yml up`؛ alembic از `backend/` روی 5434.
