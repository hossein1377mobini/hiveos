# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-10 (S3+S4 کامل؛ S5 تا حد امکان بدون PO اجرا شد — main = `da1dfc8`)

## شروع سشن جدید از اینجا — تسک‌های باز قبل از ریویو PO

1. **S3 کامل (T-S3-1..7؛ `reports/tasks/2026-09-10-T-S3-*.md` + `S3-summary.md`).** 176 تست.
2. **S4 کامل (T-S4-1..7 پنل ادمین epic-16؛ `2026-09-10-T-S4-*.md`).** 179 تست. مهاجرت 0018 (system_settings).
3. **S5 (بدون PO):** T-S5-1 چک‌لیست RG-01..22 (`2026-09-10-T-S5-1.md` — 15 PASS/2 PARTIAL/3 FAIL)، T-S5-2 گاردریل RG-18 (182 تست)، T-S5-3 wrapper ویندوزی، T-S5-5 سناریو Locust (اجرا → staging). **T-S5-4 (پراموت به prod) نیازمند تأیید صریح PO — انجام نشد.**
4. **بازهای عامل بعدی:** US-1207 subscription (RG-21)، T-S3-8 درگاه آنلاین، UI epic-10 (بنر/شارژ/چت — RG-14/15/16/09)، اجرای تست بار روی staging، لندینگ نهایی.
5. گزارش‌ها در `hive/reports/tasks/` — ریویو خارجی/اعمال نظرات/تأیید نهایی همه برای PO پس از S5 خالی است.
   | تسک | خلاصه | شواهد |
   |-----|-------|-------|
   | T-S2-1 | مدل KnowledgeSource/Asset + آپلود مستقیم (US-201) | merge `95ff49b`؛ `2026-09-10-T-S2-1.md` |
   | T-S2-2 | پویش زمان‌بندی‌شده/دستی + تشخیص تغییر + تاریخچه (US-202) | merge `9d02116`؛ `2026-09-10-T-S2-2.md` |
   | T-S2-3 | صف پردازش + dedup + Cancel/Retry (US-203/214) | merge `89825fd`؛ `2026-09-10-T-S2-3.md` |
   | T-S2-4 | Magic-byte classify + استخراج PDF/DOCX/CSV + worker (US-205/206) | merge `6e5b5d7`؛ `2026-09-10-T-S2-4.md` |
   | T-S2-5 | Normalize + Chunking + Metadata bag (US-208/210/211) | merge `426e852`؛ `2026-09-10-T-S2-5.md` |
   | T-S2-6 | bge-m3/pgvector HNSW + جستجوی معنایی (US-212/213/227) | merge `26d52df`؛ `2026-09-10-T-S2-6.md` |
   | T-S2-7 | US-241 سفت‌سازی + درگاه صفر-اعتبار (seam) | merge `0766a9a`؛ `2026-09-10-T-S2-7.md` |
2. **مهاجرت‌ها تا 0013** (0008 assets، 0009 scan_history، 0010 processing_jobs، 0011 classification، 0012 chunks+metadata، 0013 pgvector+embedding HNSW) — همه بازگشت‌پذیر؛ pgvector 0.8.6 در ایمیج dev موجود است.
3. **ریویو PO پس از S5:** بخش‌های «گزارش ریویو خارجی / اعمال نظرات / تأیید نهایی» گزارش‌های T-S1-5..T-S2-7 خالی برای PO؛ سؤالات باز هر گزارش در همان فایل + خلاصه در `hive/reports/tasks/2026-09-10-S2-summary.md`.
4. **T-S5-4 (پراموت prod) همچنان نیازمند تأیید صریح PO.**
5. نکات فنی مهم S2: توکن localStorage؛ `EMBEDDING_PROVIDER=mock` در tests (conftest) — استیجینگ برای provider=local نیاز به sentence-transformers + وزن bge-m3 دارد (نصب شد؛ اجرای مدل روی هاست dev تأیید نشده)؛ OCR بدون tesseract → needs_review (OCR_UNAVAILABLE) نه failed؛ attribute پایتون `asset_metadata` (SQLAlchemy رزرو metadata)؛ gitignore `backend/storage/`؛ audit_session_factory برای نوشتن‌های فراتر از تراکنش شکست.
## وضعیت S1 — کامل و بسته (2026-09-10)

| تسک | خلاصه | شواهد |
|-----|-------|-------|
| T-S1-1..T-S1-4 | مدل/API سازمان+Owner، OTP، verify+نشست ۷روزه | گزارش‌های `hive/reports/tasks/2026-09-10-T-S1-{1,2,3,4}.md` (ریویوشده قبلی) |
| T-S1-5 | ورود username+password + قفل ۱۵دقیقه‌ای + logout (US-009) | merge `e591924`؛ `2026-09-10-T-S1-5.md` |
| T-S1-7 | Workspace init (US-004) + Brain init + قالب پرامپت (US-005/US-1609) | merge‌های `064f697`/`b8f1a0d`؛ `2026-09-10-T-S1-7.md` — **توجه: بخش workspace اول با نام شاخه T-S1-6 اشتباه merge شد؛ گزارش در T-S1-7 ادغام و شفاف شد** |
| T-S1-6 | بازیابی رمز با OTP (US-010) — سه endpoint + ابطال نشست‌ها | merge `585ec3d`؛ `2026-09-10-T-S1-6-password-reset.md` |
| T-S1-8 | فولدر Ingestion + Resume onboarding (C2) + انقضای Pending (C3) | merge `398bb15`؛ `2026-09-10-T-S1-8.md` |
| T-S1-9 | اتصال ماک‌آپ‌های bootstrap به API (React، مسیریابی از `next_step`) | merge `5dc45c2`؛ `2026-09-10-T-S1-9.md` |

نکات فنی S1 (برای ریویو PO): `ingestion_allowed_roots` در staging/prod باید ست شود؛ ماک‌آپ 03 باید به ۶ خانه اصلاح شود (تضاد با US-003)؛ conftest حالا هر ۵ limiter را ریست می‌کند؛ نوشتن وضعیت‌های «شکست» و رویدادهای شکست از طریق `audit_session_factory` (NullPool).

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
