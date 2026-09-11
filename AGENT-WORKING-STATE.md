# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-11 (رفع یافته‌های ریویو خارجی v0.1 — main = `00ae41d`؛ 202 تست backend + 13 vitest + tsc/build سبز؛ مهاجرت‌ها تا 0022)

## وضعیت فعلی (دستور PO: «هیچ چیز بازی نماند؛ من فقط در پنل ادمین ست می‌کنم»)

7. **رفع یافته‌های ریویو خارجی v0.1** (`00ae41d`): B1–B7 / H1–H3 / S1–S13 بسته شدند — جلسات ادمین در DB (`admin_sessions`، 0021)، fail-fast اعتبارات پیش‌فرض در non-dev، کیف پول اتمیک + UNIQUE(org)، resolve مسیر انجمستون، اسکیمای settings، OTP ثابت‌زمان، binding/مرز SSE + TTL/cap، partial unique index اسکن (0022). رگرسیون: `tests/test_review_remediation.py` (8 تست). گزارش: `hive/reports/tasks/2026-09-11-review-remediation.md`.
8. **منده‌های PO**: T-S5-4 (تأیید صریح حضور محصول)، provisioning سرور استیج، کلید‌ها/پلن‌های پنل، محتوای لندینگ، دامنه.
9. **استیجینگ مستقر** (2026-09-11): `hiveos-staging` 193.93.169.136 — DB کانتینر + api `hiveos/api:staging-0e01c84` + nginx هاست (SPA+proxy)؛ 27 جدول، سموک پنل (login/logout/revoke) سبز. جزئیات: `hive/reports/tasks/2026-09-11-staging-server-deploy.md`. TLS + دامنه موکول PO.

1. **runtime از پنل تغذیه می‌شود** (`7f99b49`): کلاینت openai-compatible از `providers_pricing` پنل (base_url/api_key)، allowlist (US-1601)، نرخ اعتبار (US-1203)، قالب پرامپت (system/user_template). `agenerate`/`aroute_model` در `backend/llm.py`.
2. **پنل ادمین UI کامل** (`6f08aa0`): `/admin` — ورود، تنظیمات (۴ کلید JSON)، سازمان‌ها + اعتبار دستی + **پلن/تمدید**، درخواست‌های شارژ (تأیید/رد)، وضعیت سامانه.
3. **حلقهٔ شارژ T-S3-8** (`6f08aa0`): `POST /wallet/charge-request` → تأیید ادمین → شارژ اتمی + audit. جدول 0019 `charge_requests`. درگاه خارجی عمداً باز (جای provider خالی برای PO).
4. **UI epic-10**: چت (`11def57` — ریل جلسات، حباب‌ها، منابع، بنر صفر-اعتبار، کمپوزر قفل تا شارژ) + دانش (`3b2b4b0` — آپلود چندفایلی، پویش اکنون، جدول اسناد با بج وضعیت) + کیف‌پول (`6f08aa0`).
5. **اشتراک US-1207** (`2f6b379`): مهاجرت 0020 (`organizations.plan/plan_expires_at`)، `POST /admin/organizations/{id}/subscription` (days=0 تعلیق فوری)، دروازه 402 `SUBSCRIPTION_EXPIRED` هنگام ساخت execution، صفحهٔ اشتراک.
6. **بستهٔ استقرار** (`5ab47fe`): `deploy/` (Dockerfile + compose استیج db/backend/nginx + nginx.conf + .env.example + deploy.sh)، `scripts/ingest_watcher.py` (RG-03 آپلود خودکار پوشه)، wrapper کامل (`-Backup` pg_dump تست‌شده / `-Restart` / `-WatchIngestion`).
7. گزارش‌ها: `hive/reports/tasks/2026-09-11-T-S5-2-*.md` (provider-settings، admin-ui-charge-loop، chat-ui، knowledge-ui، subscription، deploy-bundle).

## باقی (پیش از تست staging توسط PO)

- پایان build استک docker (در جریان؛ شواهد e2e استک در گزارش بعدی)
- RG-20: اجرای Locust روی staging (بعد از آپلود سرور PO)
- RG نهایی (re-run کامل) + لندینگ (متن از PO)
- T-S5-4 پراموت به prod — نیازمند تأیید صریح PO
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
