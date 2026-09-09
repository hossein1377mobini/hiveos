# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-10 (پایان سشن S0 — آماده‌سازی سشن جدید)

## شروع سشن جدید از اینجا

1. تسک بعدی: **T-S0-5 پایه فرانت** (Vite/React + layout + پروکسی به API — §۸ development-workflow)؛ شاخه `task/T-S0-5-frontend-base` از main.
2. خواندنی‌ها قبل از کد: `standards/setup-guide.md`، `ui-mockups/v0.1/_specs/dev-guidelines-v0.1.md`، `standards/standards-coding-standards-v10.md`، DoD.
3. چرخه: کد+تست+خودریویو → گزارش `hive/reports/tasks/<تاریخ>-T-S0-5.md` → ریویو خارجی PO → merge فقط با تأیید PO.
4. دستورهای ایستاده PO: پایین همین فایل.

## وضعیت S0 — کامل (2026-09-10)

| تسک | وضعیت | شواهد |
|-----|-------|-------|
| T-S0-1 اسکلت+CI | merge شده؛ ریویو نوبت ۱ اعمال؛ R1-1 بسته (CI run سبز) | PR #2، runs 34411938557/34412023587 |
| T-S0-2 FastAPI | merge شده؛ ریویو نوبت ۱+۲ اعمال (version از metadata، CORS validator، DB_URL fail-fast؛ 15 tests) | کامیت‌های c1274a9/9ba45ea |
| T-S0-3 Compose+Alembic | merge شده؛ ریویو نوبت ۱ اعمال (secrets از env، حذف prod overlay، sync-url helper)؛ E2E سبز | کامیت bf843c0 |
| T-S0-4 Deploy pipeline | merge شده؛ ریویو نوبت ۱+۲ اعمال (root guard، تک workflow، .dockerignore با اثبات NO-LEAK، USER 10001 non-root)؛ **deploy خودکار سبز** | run 34416119083 — staging روی `ci-149cf43...` |
| یکپارچه‌سازی | PR #2 merge شد → main = `cebf0e0`؛ CI backend روی main سبز (run 34415142318) | — |

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
