# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-10 (اعمال ریویو نوبت ۱ S0)

## دستورهای ایستاده PO (2026-09-10)

1. **مبنای کار = اسناد فنی `hive/`** — هیچ تصمیمی خارج از ADR/version-scope/development-workflow گرفته نشود؛ ابهام = سؤال از PO، نه حدس.
2. **ادامه از جایی که مرحله قبل مانده** — در زمان این سشن: T-S0-4 تمام، ریویو S0 اعمال شد؛ بعدی T-S0-5.
3. **ریویو پس از پایان S0** — PO دستور «شروع ریویو» می‌دهد؛ عامل محل گزارش‌ها + شاخه‌ها + کامیت‌ها را به ریویوئر می‌دهد. ریویو نوبت ۱ آمد و اعمال شد (2026-09-10).
4. **سرورها خاموش بمانند** مگر فقط برای زمان لازم. SSH از همین سیستم: کلید `C:\Users\Hossein Mobini\.ssh\hiveos_key` + میان‌برهای `hiveos-staging` / `hiveos-prod` در config.
5. **Kaneo حذف شد (2026-09-10)** — کانتینرها + والیوم + ایمیج + network پاک شدند؛ orphan `hiveos-redis` و ایمیج‌های hiveos قدیمی pre-transfer هم. native postgres ویندوزی روی 5432 مال PO است — دست نزن. DB اپ روی 5434 می‌ماند.
6. **هیچ secret در گیت** (ADR-022). کلید/توکن‌ها نزد PO یا در secrets سرورها.

## وضعیت S0 (2026-09-10 — پس از ریویو نوبت ۱)

| تسک | وضعیت | محل |
|-----|-------|-----|
| T-S0-1 اسکلت+CI | ریویو اعمال شد (4536bf1: uv sync --frozen، حذف .gitkeepها). **R1-1 باز: شواهد CI run واقعی — با اولین PR/push main بسته می‌شود.** | task/T-S0-1 (روی GitHub) |
| T-S0-2 FastAPI | ریویو اعمال شد (c1274a9: نسخه از metadata + تست، CORS از settings + ۴ تست، 9 passed). | task/T-S0-2 (روی GitHub) |
| T-S0-3 Compose+Alembic | ریویو اعمال شد (bf843c0: secrets از env + infrastructure/.env gitignored، حذف prod overlay و nginx.conf، helper sync-url + تست، alembic.ini پاک؛ E2E سبز). | task/T-S0-3 (روی GitHub) |
| T-S0-4 Deploy pipeline | ریویو اعمال شد (eecc805: گارد root، تک-workflow، حذف ci.yml، README مسیر واحد + محدودیت rollback/migration؛ سینک staging + deploy مجدد سبز). | task/T-S0-4 (روی GitHub) |
| T-S0-5 فرانت پایه | شروع نشده — بعدی | — |

## وضعیت ریویو و بلاکرهای merge (2026-09-10)

- ریویو نوبت ۱ هر ۴ تسک آمد و اعمال شد؛ ثبت در بخش «اعمال نظرات» هر گزارش (hive/reports/tasks/).
- باز فعال: فقط rollback-migration (الزام S2، در README ثبت). R1-1 بسته شد — CI run 34411938557 سبز روی PR #2 (probe/s0-integration).
- **گیر merge حل‌شدنی شد:** PR #2 (`probe/s0-integration` → main) باز است و CI سبز؛ تاریخچه‌ی main placeholder با merge `effc5c5` پذیرفته شد. merge PR = جایگزینی کامل main (تأیید نهایی PO لازم).
- دسترسی گیت فعال شد؛ push شاخه‌ها موفق. Secrets ریپو (`STAGING_SSH_KEY`/`STAGING_HOST`) هنوز ست نشده (API با PAT فعلی 403).
- فردوسی پنل: 80/443 سمت پنل برای origin بسته (ufw باز، ولی پکت نمی‌رسد — کانتر صفر). باید در پنل باز شود. Arvan edge/SSL سالم (Let's Encrypt تا 2026-12-08).

## نکات فنی ماندگار S0

- Deploy path: GH Actions → build → docker save/scp/load (بدون registry) → remote-deploy.sh (env از secret سرور، alembic، healthcheck :8100+:80، rollback خودکار). `ci-deploy.yml` تنها workflow است.
- Staging stack: فقط api در compose (project hiveos-app) به شبکه خارجی db (hiveos_default) وصل؛ host nginx :80 proxy → 127.0.0.1:8100. وضعیت: tag manual-2026-09-10 در حال اجرا، migration 0001 اعمال، health سبز. prod: فقط DB stack.
- CORS: `CORS_ORIGINS` env (کاما-جدا) — خالی = deny؛ \"*\" فقط dev. APP env names بدون prefix (ENVIRONMENT/DATABASE_URL/CORS_ORIGINS).
- محدودیت ثبت‌شده: rollback فقط image — قبل از اولین migration مخرب در S2 باید گام schema بگیرد (README Known limitation).
- `to_sync_database_url` helper در config.py برای Alembic (تست‌شده).