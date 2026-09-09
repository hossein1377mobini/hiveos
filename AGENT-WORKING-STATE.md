# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-10 (سشن T-S0-4)

## دستورهای ایستاده PO (2026-09-10)

1. **مبنای کار = اسناد فنی `hive/`** — هیچ تصمیمی خارج از ADR/version-scope/development-workflow گرفته نشود؛ ابهام = سؤال از PO، نه حدس.
2. **ادامه از جایی که مرحله قبل مانده** (T-S0-4 در زمان این سشن).
3. **ریویو بعد از پایان S0** شروع می‌شود — قبل از آن گزارش‌ها فقط نوشته می‌شوند، ریویو خارجی منتظر می‌ماند. PO دستور «شروع ریویو» می‌دهد؛ عامل باید محل گزارش‌ها + شاخه‌ها + کامیت‌ها را به ریویوئر بدهد.
4. **سرورها خاموش بمانند** مگر فقط برای زمان لازم. هر دو سرور فردوسی (staging 193.93.169.136 / prod 193.93.169.204) با SSH key همین سیستم (C:\Users\Hossein Mobini\.ssh\hiveos_key + config با میان‌بر hiveos-staging / hiveos-prod) در دسترس‌اند.
5. **Kaneo حذف شد/شدنی است** — PO استفاده نمی‌کند؛ کانتینر/والیوم/ایمیج آن قابل پاک‌سازی. native postgres ویندوزی روی 5432 مال PO است — دست نزن. DB اپ روی 5434 می‌ماند.
6. **هیچ secret در گیت** (ADR-022). کلید/توکن‌ها نزد PO (فایل transfer روی Desktop PO) یا در secrets سرورها.

## وضعیت S0 (آخرین به‌روزرسانی 2026-09-10)

| تسک | وضعیت | محل |
|-----|-------|-----|
| T-S0-1 اسکلت+CI | ساخته‌شده، منتظر ریویو | branch task/T-S0-1 + گزارش reports/tasks/2026-09-09 |
| T-S0-2 FastAPI | ساخته‌شده، منتظر ریویو | branch task/T-S0-2 + گزارش |
| T-S0-3 Compose+Alembic | ساخته‌شده، منتظر ریویو | branch task/T-S0-3 + گزارش |
| T-S0-4 Deploy pipeline | **پیاده + تست دستی روی staging موفق (2026-09-10)** | branch task/T-S0-4 + گزارش reports/tasks/2026-09-10 |
| T-S0-5 فرانت پایه | شروع نشده | — |

## نکات فنی ماندگار S0

- Deploy path: GH Actions → build image → docker save/scp/load (بدون registry) → remote-deploy.sh (env از secret سرور، alembic، healthcheck :8100+:80، rollback خودکار).
- Staging stack: فقط api در compose (project hiveos-app) به شبکه خارجی db (hiveos_default) وصل است؛ host nginx :80 proxy → 127.0.0.1:8100؛ certbot/TLS بعد از تصمیم Arvan Cloud.
- وضعیت deploy اول staging: tag manual-2026-09-10، migration 0001 اعمال شد، health سبز. prod: فقط DB stack؛ app در T-S5-4 پراموت می‌شود.
- بلاکرهای push به GitHub: PAT فعلی scope `workflow` ندارد (push شاخه‌های دارای .github/workflows رد می‌شود) + secrets API 403. نیازمند PAT جدید (Contents+Actions+Secrets+Workflows) یا اقدام UI توسط PO. شاخه‌های T-S0-1..3/4 محلی آماده push‌اند.
- force-push main (جایگزینی کامیت placeholder قدیمی 021afc1 با تاریخچه T-S0-1..) نیازمند تأیید PO است.
