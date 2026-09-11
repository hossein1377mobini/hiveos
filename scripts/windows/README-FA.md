# HiveOS v0.1 — نسخهٔ ویندوزی (راهنمای فارسی)

## پیش‌نیاز
- **Docker Desktop** (روشن باشد)
- **Python 3.11** روی PATH (دستور `py -3.11` کار کند)

## اجرا (یک دستور)
در پوشهٔ باز‌شدهٔ bundle، PowerShell را باز کنید:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\INSTALL-AND-RUN.ps1
```

پنجره‌های API و UI باز می‌شوند. بعد از چند ثانیه:

| آدرس | توضیح |
|---|---|
| http://127.0.0.1:8080 | اپلیکیشن (UI) |
| http://127.0.0.1:8080/admin | پنل ادمین |
| http://127.0.0.1:8000/api/health | سلامت API |

- ورود پنل به‌صورت محلی (dev): `system-admin` / `system-admin-dev`
- اولین کاربر اپ: از UI ثبت‌نام سازمان → مالک (روال US-001/US-002)
- همهٔ وابستگی‌ها از پوشهٔ `deploy\_wheels` نصب می‌شوند — **نیازی به اینترنت نیست.**

## ابزارهای عملیاتی (run-hiveos.ps1)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\run-hiveos.ps1 -Backup        # بکاپ pg_dump → backups/
powershell -ExecutionPolicy Bypass -File scripts\windows\run-hiveos.ps1 -Restart       # ری‌استارت DB/API
powershell -ExecutionPolicy Bypass -File scripts\\windows\run-hiveos.ps1 -WatchIngestion C:un-hiveos.ps1 -WatchIngestion C:\docs -WatcherUser <user> -WatcherPass <pass>
```

## توقف کامل
پنجره‌های API و UI را ببندید و:
```powershell
docker compose -f docker-compose.windows.yml down
```
(دادهٔ دیتابیس در `.pgdata\` می‌ماند.)

## عیب‌یابی
- «hiveos-db container is not running» → Docker Desktop را روشن کنید و دوباره INSTALL-AND-RUN را بزنید.
- پورت 5434/8080/8000 اشغال است → برنامهٔ دیگر را ببندید.
- مدل embedding به‌صورت پیش‌فرض `mock` است (تست بدون GPU)؛ تنظیم از پنل ادمین.
