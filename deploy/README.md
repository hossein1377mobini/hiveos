# HiveOS v0.1 — استقرار استیج (zero-open)

## یک‌بار، روی ماشین ساخت (ویندوز/هر ماشین با اینترنت)

1. فرانت: `cd frontend && npm ci && npx vite build`
2. وندور چرخ‌های لینوکسی (buildkit داخل کانتینر به pypi دسترسی ندارد؛ بستهٔ آفلاین می‌سازیم):

```sh
cd backend
py -3.11 -m pip download . hatchling uvloop "uvicorn[standard]" cuda-toolkit==13.0.3 triton \
  -d ../deploy/_wheels --only-binary=:all: \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 \
  --python-version 3.11 --implementation cp

# torch CPU (بدون وابستگی cuda):
py -3.11 -m pip download torch --index-url https://download.pytorch.org/whl/cpu \
  -d ../deploy/_wheels --only-binary=:all: \
  --platform manylinux_2_28_x86_64 --python-version 3.11 --implementation cp
```

## سرور PO

```sh
cp deploy/.env.example deploy/.env   # رمز DB + رمز پنل ادمین + پورت
sh deploy/deploy.sh                  # build + up + health-check
# → http://<server>/            اپ
# → http://<server>/admin       پنل ادمین (تنها جای ست‌کردن کلیدها/پلن‌ها توسط PO)
```

## یادداشت‌ها

- مهاجرت‌ها هنگام استارت کانتینن backend خودکار اجرا می‌شوند (idempotent).
- `ENVIRONMENT=staging` ⇒ اگر `DATABASE_URL` ست نشده باشد، backend صریح fail می‌کند (نه رفتن به localhost).
- `backups/` و `deploy/_wheels/` هرگز وارد گیت نمی‌شوند.
