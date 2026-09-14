# استقرار HiveOS — مسیر رسمی

این پوشه دو فایل دارد که **اجرا نمی‌شوند** و فقط گمراه‌کننده‌اند. پیش از
تغییر هر چیزی، بخش «تله» را بخوانید.

## مسیر رسمی (همان چیزی که واقعاً اجرا می‌شود)

| کار | فایل |
| --- | --- |
| ایمیج بک‌اند | `infrastructure/api.Dockerfile` |
| استک محلی/توسعه | `infrastructure/docker-compose.yml` |
| استک استیج | `infrastructure/docker-compose.staging.yml` |
| کامپوز مستقر روی سرور | `/opt/hiveos/app/docker-compose.staging.yml` |
| CI و دیپلوی | `.github/workflows/ci-deploy.yml` |

ساخت ایمیج:

```sh
docker build -f infrastructure/api.Dockerfile -t hiveos/api:<tag> .
```

`infrastructure/api.Dockerfile` بر پایهٔ `uv` است و وابستگی‌ها را از
`uv.lock` می‌گیرد (`--extra local-ml`). ماشین ساخت به اینترنت نیاز دارد؛
**سرور نه** — انتقال با `docker save` / `docker load` انجام می‌شود.

## تله‌ها

1. **`deploy/Dockerfile` استفاده نمی‌شود.** با `python:3.11-slim` و
   wheelhouse دستی کار می‌کند. نسخهٔ قدیمی این README وندور کردن `torch` و
   `triton` را توصیه می‌کرد؛ همان دستور ایمیج را از ۱٫۴۳GB به ۲٫۰۵GB رساند.
   `local-ml` فقط `onnxruntime` و `transformers` می‌خواهد — گراف‌های int8
   از `/opt/models` مانت می‌شوند و هیچ‌وقت داخل ایمیج نمی‌روند.

2. **`deploy/docker-compose.staging.yml` استفاده نمی‌شود.** فقط
   `deploy/Dockerfile` را صدا می‌زند.

3. **دو فایل با نام یکسان.** `infrastructure/docker-compose.staging.yml`
   (در گیت) با `/opt/hiveos/app/docker-compose.staging.yml` (دست‌ساز روی
   سرور) یکی نیستند. فایل سرور تنها نسخهٔ مستقر است و
   `ports`/`networks`/`volumes` مخصوص خودش را دارد.
   **هرگز فایل گیت را روی آن کپی نکنید.**

## استقرار روی سرور استیج

سرور به PyPI و رجیستری دسترسی ندارد. زنجیرهٔ انتقال:

```sh
# روی ماشین ساخت
docker build -f infrastructure/api.Dockerfile -t hiveos/api:<tag> .
docker save hiveos/api:<tag> -o _img.tar

# انتقال (gzip روی این tar فایده ندارد — خروجی بزرگ‌تر می‌شود)
scp _img.tar ubuntu@<host>:/home/ubuntu/

# روی سرور
sudo docker load -i /home/ubuntu/_img.tar
sudo sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=<tag>/' /opt/hiveos/app/.env
cd /opt/hiveos/app && sudo docker compose -f docker-compose.staging.yml up -d
```

فرانت روی هاست nginx سرو می‌شود، نه در کانتینر:

```sh
cd frontend && npm run build
tar -czf _dist.tgz -C dist .
scp _dist.tgz ubuntu@<host>:/home/ubuntu/
# روی سرور: بکاپ، سپس تعویض اتمیک /var/www/hiveos/dist
```

## آدرس‌ها

- اپ: `https://hivesystem.ir/`
- پنل ادمین: `https://hivesystem.ir/admin` — تنها جای تنظیم کلیدها و پلن‌ها

## یادداشت

- مهاجرت‌ها هنگام استارت کانتینر backend خودکار اجرا می‌شوند (idempotent).
- `ENVIRONMENT=staging` ⇒ اگر `DATABASE_URL` ست نباشد، backend صریح
  fail می‌کند (به‌جای رفتن به localhost).
- `backups/`، `deploy/_wheels/` و `models/` هرگز وارد گیت نمی‌شوند.
