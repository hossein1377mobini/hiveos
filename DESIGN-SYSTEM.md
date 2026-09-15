# سیستم طراحی HiveOS — آینهٔ دستی `src/styles.css`

این فایل، آینهٔ قابل‌ویرایشِ انسانی برای فایل توکن‌های محصول است. منبع حقیقتِ ماشین همان `src/styles.css` است؛ این سند فقط آن را برای تصمیم‌گیری محصول ترجمه و فهرست می‌کند.

- منبع حقیقت (machine source of truth): `frontend/src/styles.css` — تنها جایی که مقدار واقعی توکن‌ها تعریف می‌شود.
- این فایل (human-editable mirror): `hiveos/DESIGN-SYSTEM.md` — توضیح نقش‌ها و محل ویرایش.
- اگر مقدار یا توکنی در این سند با `src/styles.css` تفاوت داشت، همیشه `src/styles.css` برنده است.

**قاعدهٔ طلایی:** هر تغییر طراحی باید در دو جا اعمال شود — مقدار توکن را در `src/styles.css` عوض کن، و همان ردیف را در جدول‌های همین فایل به‌روز کن. هیچ‌وقت فقط یکی از این دو را تغییر نده.

**پیکربندی Tailwind:** پروژه از Tailwind v4 با پیکربندی CSS-first استفاده می‌کند. هیچ فایل `tailwind.config.js` / `.ts` / `.cjs` / `.mjs` وجود ندارد (و نباید ساخته شود). کل پیکربندی داخل بلوک `@theme` در `src/styles.css` است. `frontend/components.json` هم همین را تأیید می‌کند: مقدار `tailwind.config` خالی است و `tailwind.css` به `src/styles.css` اشاره می‌کند. پلاگین `@tailwindcss/vite` در `frontend/vite.config.ts` فعال است.

---

## چطور این فایل را ویرایش کنم

1. ردیف مربوط به تغییری که می‌خواهی را در جدول‌های بخش‌های بعدی پیدا کن (یا از بخش «نگاشت: هر تغییر کجا اعمال می‌شود» در انتهای فایل شروع کن).
2. نام توکن دقیق (مثلاً `--color-accent-700`) و فایل و محدودهٔ خطی که در ستون «کجا ویرایش شود» آمده را بردار.
3. همان مقدار را در `src/styles.css` عوض کن. هرگز مقدار را مستقیم در فایل کامپوننت (`*.tsx`) به‌صورت inline ننویس.
4. همان ردیف را در جدول این فایل به‌روز کن تا سند و کد یکی بمانند.
5. اگر مقدار تازه از هیچ توکنی در `src/styles.css` قابل دسترسی نیست، اول آن توکن را در `src/styles.css` تعریف کن، بعد در این سند ردیفش را اضافه کن. هیچ مقدار inline در کامپوننت‌ها مجاز نیست — این قاعده در بالای خود `src/styles.css` هم نوشته شده است.
6. اعتبارسنجی: `npm run test:css` (اسکریپت `scripts/check-css-tokens.mjs`) بررسی می‌کند که هر کلاس توکنی به یک مقدار واقعی resolve شود، و `npm run audit:ui` (اسکریپت `scripts/ui-audit.mjs`) بررسی می‌کند که هیچ کامپوننتی از توکن فرار نکرده باشد.

نمونه‌ها:

- تغییر رنگ اکشن اصلی → `--color-accent-500` در `src/styles.css` (خط 78).
- تغییر شعاع دکمه‌ها → `--radius-control` در `src/styles.css` (خط 184).
- تغییر اندازهٔ فونت متن → `--text-body` در `src/styles.css` (خط 161).

---

## ۱) توکن‌های رنگ پایه (Primitive)

همهٔ این‌ها در بلوک `@theme` فایل `src/styles.css` (خطوط 54 تا 214) تعریف شده‌اند. پالت، سیستم طراحی Cursor است که کامل پذیرفته شده است.

### رمپ خنثی (neutral)

| توکن | مقدار hex | نقش | چه وقت استفاده شود |
| --- | --- | --- | --- |
| `--color-neutral-0` | `#ffffff` | سطح کارت | `--card`، `--popover`، `--sidebar`؛ کارت سفید که عمداً روی بوم کرم می‌نشیند |
| `--color-neutral-25` | `#fafaf7` | canvas-soft | پنل‌های IDE، کد inline، نوار سرصفحهٔ جدول |
| `--color-neutral-50` | `#f7f7f4` | canvas / کف صفحه | `--background`؛ رنگ زمینهٔ کل اپ |
| `--color-neutral-100` | `#efeee8` | hairline-soft / surface-strong | `--secondary`، `--muted`، نشستن عناصر خنثی |
| `--color-neutral-200` | `#e6e5e0` | hairline | `--border`، `--sidebar-border`؛ خطوط جداکنندهٔ کارت و جدول |
| `--color-neutral-300` | `#cfcdc4` | hairline-strong | `--border-strong`، `--input`، رنگ نوار اسکرول |
| `--color-neutral-400` | `#a09c92` | muted-soft | متن غیرفعال (disabled) |
| `--color-neutral-500` | `#807d72` | muted | زیرعنوان‌ها |
| `--color-neutral-600` | `#5a5852` | body | متن جاری پیش‌فرض؛ `--muted-foreground` |
| `--color-neutral-700` | `#3d3c37` | رمپ میانی | رزرو؛ بدون نقش فعال در `:root` |
| `--color-neutral-800` | `#26251e` | ink | مشکی گرم نزدیک — نه `#000` |
| `--color-neutral-900` | `#26251e` | ink | `--foreground`، `--card-foreground`، `--sidebar-foreground` |

### رمپ اکسنت (Cursor Orange)

| توکن | مقدار hex | نقش | چه وقت استفاده شود |
| --- | --- | --- | --- |
| `--color-accent-50` | `#fdeee6` | tint | `--accent`، `--sidebar-accent`؛ پس‌زمینهٔ حالت انتخاب‌شده |
| `--color-accent-100` | `#fbdccd` | tint میانی | رزرو |
| `--color-accent-200` | `#f6b699` | tint | رزرو |
| `--color-accent-300` | `#f28a5e` | tint تیره | رزرو |
| `--color-accent-400` | `#f56b30` | حلقهٔ فوکوس | `--shadow-focus` (خط 212) |
| `--color-accent-500` | `#f54e00` | نارنجی Cursor — ولتاژ برند | مصرف کم: `--ring`، `--sidebar-primary`، `--sidebar-ring`، `--chart-1`، نمودارها و فیل‌های تزئینی. به‌عنوان متن/پس‌زمینهٔ اکشن، AA را رد می‌کند |
| `--color-accent-600` | `#d04200` | primary-active | رزرو / حالت فشرده |
| `--color-accent-700` | `#a83600` | عمق اکشن | `--primary`، `--accent-foreground`، `--sidebar-accent-foreground` |
| `--color-accent-800` | `#7d2900` | عمق بیشتر | `--primary-hover` |
| `--color-accent-900` | `#521b00` | تیره‌ترین | رزرو |

### نقش‌های وضعیت (status)

| توکن | مقدار hex | نقش | چه وقت استفاده شود |
| --- | --- | --- | --- |
| `--color-success` | `#1f8a65` | متن موفقیت | متن وضعیت موفق |
| `--color-success-strong` | `#166b4e` | نسخهٔ قوی | تأکید بیشتر |
| `--color-success-bg` | `#e8f5ef` | سطح موفقیت | پس‌زمینهٔ بنر/بج موفق |
| `--color-success-border` | `#b9e2d1` | حاشیهٔ موفقیت | کادر بنر موفق |
| `--color-warning` | `#8a5a12` | متن هشدار | متن وضعیت هشدار |
| `--color-warning-strong` | `#b7791f` | نسخهٔ قوی | تأکید بیشتر |
| `--color-warning-bg` | `#fbf1e3` | سطح هشدار | پس‌زمینهٔ بنر/بج هشدار |
| `--color-warning-border` | `#eed9b6` | حاشیهٔ هشدار | کادر بنر هشدار |
| `--color-error` | `#ba284d` | متن خطا | متن وضعیت خطا؛ جایگزین `#cf2d56` که روی سطح‌های روشن کمی زیر AA می‌افتاد |
| `--color-error-strong` | `#a81f42` | نسخهٔ قوی | `--destructive` |
| `--color-error-bg` | `#fdecef` | سطح خطا | پس‌زمینهٔ بنر/بج خطا |
| `--color-error-border` | `#f7c3d0` | حاشیهٔ خطا | کادر بنر خطا |
| `--color-info` | `#2b3a73` | متن اطلاع | متن وضعیت اطلاع |
| `--color-info-strong` | `#232f5e` | نسخهٔ قوی | تأکید بیشتر |
| `--color-info-bg` | `#eef1fb` | سطح اطلاع | پس‌زمینهٔ بنر/بج اطلاع |
| `--color-info-border` | `#c4cdf0` | حاشیهٔ اطلاع | کادر بنر اطلاع |

نکته: hue های هشدار و اطلاع در سند Cursor تعریف نشده‌اند و با success/error هم‌آهنگ شده‌اند؛ عمداً نارنجی دومی ساخته نشد تا با اکسنت برند تداخل نکند.

### رنگ‌های دسته‌بندی (نمودار و نشانگر مرحله)

| توکن | مقدار hex | نقش | چه وقت استفاده شود |
| --- | --- | --- | --- |
| `--color-teal` | `#1f8a65` | hue دسته‌بندی | سری نمودار، `--chart-2` |
| `--color-teal-soft` | `#e8f5ef` | سطح teal | بج/دات teal |
| `--color-amber` | `#c08532` | hue دسته‌بندی | سری نمودار، `--chart-3` |
| `--color-amber-soft` | `#fbf1e3` | سطح amber | بج/دات amber |
| `--color-violet` | `#c0a8dd` | hue دسته‌بندی | سری نمودار، `--chart-4` |
| `--color-violet-soft` | `#f3eefa` | سطح violet | بج/دات violet |
| `--color-rose` | `#cf2d56` | hue دسته‌بندی | رنگ Cursor برای rose |
| `--color-rose-soft` | `#fdecef` | سطح rose | پس‌زمینهٔ rose |
| `--color-sky` | `#9fbbe0` | hue دسته‌بندی | سری نمودار، `--chart-5` |
| `--color-sky-soft` | `#eef3fb` | سطح sky | پس‌زمینهٔ sky |
| `--color-peach` | `#dfa88f` | hue دسته‌بندی | تایم‌لاین مرحلهٔ «در صف» |
| `--color-peach-soft` | `#fbeee8` | سطح peach | پس‌زمینهٔ peach |
| `--color-mint` | `#9fc9a2` | hue دسته‌بندی | تایم‌لاین مرحلهٔ «در حال پردازش» |
| `--color-mint-soft` | `#eef6ef` | سطح mint | پس‌زمینهٔ mint |

این‌ها عمداً از نقش‌های وضعیت جدا هستند: سری teal در نمودار به معنی «موفقیت» نیست.

---

## ۲) توکن‌های معنایی (shadcn)

در بلوک `:root` فایل `src/styles.css` (خطوط 217 تا 271) تعریف شده‌اند و در `@theme inline` (خطوط 274 تا 329) به Tailwind صادر می‌شوند.

| توکن | به چه چیزی map شده | معنا |
| --- | --- | --- |
| `--background` | `var(--color-neutral-50)` | کف صفحه: کرم `#f7f7f4` |
| `--foreground` | `var(--color-neutral-900)` | رنگ متن اصلی: ink `#26251e` |
| `--card` | `var(--color-neutral-0)` | سطح کارت: سفید |
| `--card-foreground` | `var(--color-neutral-900)` | متن روی کارت |
| `--popover` | `var(--color-neutral-0)` | سطح شناور (منو، پاپ‌اور) |
| `--popover-foreground` | `var(--color-neutral-900)` | متن روی پاپ‌اور |
| `--primary` | `var(--color-accent-700)` = `#a83600` | رنگ اکشن اصلی. **اکسنت-۷۰۰ است، نه اکسنت-۵۰۰** |
| `--primary-foreground` | `#ffffff` | متن روی اکشن اصلی |
| `--primary-hover` | `var(--color-accent-800)` | حالت hover اکشن اصلی |
| `--secondary` | `var(--color-neutral-100)` | سطح ثانویه |
| `--secondary-foreground` | `var(--color-neutral-900)` | متن روی سطح ثانویه |
| `--accent` | `var(--color-accent-50)` | سطح انتخاب‌شده / hover خنثی مایل به اکسنت |
| `--accent-foreground` | `var(--color-accent-700)` | متن روی `--accent` |
| `--muted` | `var(--color-neutral-100)` | سطح خنثی/غیرفعال |
| `--muted-foreground` | `var(--color-neutral-600)` | متن کم‌رنگ، توضیح، متادیتا |
| `--destructive` | `var(--color-error-strong)` = `#a81f42` | اکشن خطرناک/حذف |
| `--destructive-foreground` | `#ffffff` | متن روی destructive |
| `--border` | `var(--color-neutral-200)` | hairline استاندارد |
| `--border-strong` | `var(--color-neutral-300)` | hairline قوی‌تر |
| `--input` | `var(--color-neutral-300)` | حاشیهٔ فیلد ورودی |
| `--ring` | `var(--color-accent-500)` = `#f54e00` | رنگ حلقهٔ فوکوس |
| `--chart-1` | `var(--color-accent-500)` | سری ۱ نمودار |
| `--chart-2` | `var(--color-teal)` | سری ۲ نمودار |
| `--chart-3` | `var(--color-amber)` | سری ۳ نمودار |
| `--chart-4` | `var(--color-violet)` | سری ۴ نمودار |
| `--chart-5` | `var(--color-sky)` | سری ۵ نمودار |
| `--sidebar` | `var(--color-neutral-0)` | سطح سایدبار |
| `--sidebar-foreground` | `var(--color-neutral-900)` | متن سایدبار |
| `--sidebar-primary` | `var(--color-accent-500)` | نشان/آواتار سایدبار |
| `--sidebar-primary-foreground` | `#ffffff` | متن روی `--sidebar-primary` |
| `--sidebar-accent` | `var(--color-accent-50)` | ردیف فعال/هاور سایدبار |
| `--sidebar-accent-foreground` | `var(--color-accent-700)` | متن ردیف فعال سایدبار |
| `--sidebar-border` | `var(--color-neutral-200)` | hairline سایدبار |
| `--sidebar-ring` | `var(--color-accent-500)` | حلقهٔ فوکوس داخل سایدبار |
| `--radius` | `var(--radius-card)` = `12px` | شعاع پایه که نردبان `--radius-sm/md/lg/xl/2xl` از آن ساخته می‌شود |

### چرا `--primary` اکسنت-۷۰۰ است و نه اکسنت-۵۰۰

`#f54e00` (که `--color-accent-500` است) به‌عنوان سطحِ متن سفید فقط کنتراست ۳٫۵۲:۱ می‌دهد و به‌عنوان ink روی tint اکسنت ۳٫۱:۱ — هر دو زیر کف AA (۴٫۵:۱). ابزار axe-core این را روی هفت مسیر محصول علامت زد. `--primary` نقش *تعاملی* است (پر شدن دکمه، متن لینک)، پس عمق همان hue را می‌گیرد: سفید روی `--primary` کنتراست ۶٫۵۸:۱ دارد و به‌عنوان متن روی همهٔ سطح‌های روشن بالای ۵٫۸:۱ می‌خواند.

رنگ زندهٔ `#f54e00` حذف نشده: به‌عنوان `--color-accent-500` برای وردمارک، حلقهٔ فوکوس (`--ring`، `--sidebar-ring`، `--shadow-focus`) و پرهای تزئینی/نمودار باقی می‌ماند — دقیقاً همان نقش «مصرف کم» که سیستم طراحی برایش تعریف کرده است.

---

## ۳) مقیاس تایپ

تعریف‌شده در `@theme` فایل `src/styles.css` (خطوط 126 تا 171). وزن‌ها در خطوط 173 تا 177.

| توکن | اندازه | line-height | وزن | نقش |
| --- | --- | --- | --- | --- |
| `--text-display` | `2rem` (32px) | `1.3` | `400` | هیرو صفحه، مقدار KPI در پنل ادمین |
| `--text-title` | `1.375rem` (22px) | `1.4` | `400` | عنوان صفحه (معادل display-sm در Cursor) |
| `--text-heading` | `1.125rem` (18px) | `1.45` | `600` | عنوان بخش یا کارت (title-md) |
| `--text-subheading` | `1rem` (16px) | `1.5` | `600` | زیربخش، سرصفحهٔ جدول (title-sm) |
| `--text-body` | `0.875rem` (14px) | `1.75` | `400` | متن جاری پیش‌فرض |
| `--text-caption` | `0.8125rem` (13px) | `1.65` | `400` | متن کمکی، ردیف‌های ثانویه |
| `--text-micro` | `0.6875rem` (11px) | `1.5` | `600` | بج‌ها، متادیتا، کروم جدول |

توکن‌های وزن: `--font-weight-normal` = `400`، `--font-weight-medium` = `500`، `--font-weight-demibold` = `600`، `--font-weight-bold` = `700`.

خط `body` هم در base layer (خط 344) صراحتاً `line-height: 1.75` می‌گیرد تا هر متنی که از توکن استفاده نمی‌کند هم همان فاصله را داشته باشد.

### چرا display و title روی وزن ۴۰۰ هستند

ساختاری‌ترین تصمیم تایپی Cursor این است که display روی وزن `400` می‌نشیند و رتبه‌بندی را «چشم» انجام می‌دهد، نه «وزن». همین چیزی است که در سند با نام «magazine voice» یاد شده و دلیل اینکه سطح Cursor هیچ‌وقت دادوبیداد نمی‌کند. نمایش با وزن `800` که HiveOS قبلاً داشت، بزرگ‌ترین عامل این بود که محصول مثل یک قالب ادمین پیش‌فرض خوانده شود؛ حالا جایگزین شده است. نیمهٔ کاربردی مقیاس تغییری نکرده: نقش‌های title-md و title-sm در Cursor وزن `600` دارند، پس عنوان بخش و کارت وزن واقعی خود را نگه می‌دارد و فقط پله‌های بزرگ (display، title و هیرو) به `400` افتاده‌اند.

استثنای عامدانه: IRANYekanX در وزن ۴۰۰ داخل یک تیتر ۳۰ پیکسلی خوانا اما محسوس سبک‌تر از یک فونت لاتین با همان وزن است، پس پلهٔ display یک درجه بزرگ‌تر گرفته (۳۲px در برابر ۲۶px متناسب Cursor) تا عنوان صفحه محو نشود.

### نقش هر پله — و اینکه هیچ پلهٔ دیگری مجاز نیست

این جدول یک «راهنما» نیست، یک قاعده است. هر اندازهٔ فونت در محصول باید یکی از این هفت پله باشد:

| اگر عنصر … | پلهٔ درست |
| --- | --- |
| عنوان صفحه (h1 هر صفحه) | `text-title` |
| عنوان بخش یا کارت (h2) | `text-heading` |
| زیربخش، سرصفحهٔ جدول | `text-subheading` |
| متن جاری، برچسب فیلد، متن دکمه | `text-body` |
| متن کمکی، توضیح زیر فیلد، سلول ثانویهٔ جدول | `text-caption` |
| بج، متادیتا، برچسب گروه سایدبار | `text-micro` |
| فقط هیرو صفحه و مقدار KPI | `text-display` |

پله‌های Tailwind خارج از این فهرست — `text-xs`، `text-sm`، `text-base`، `text-lg`، `text-xl`، `text-2xl` — **ممنوع‌اند**، حتی وقتی اسکریپت audit آن‌ها را نمی‌گیرد. دلیلش این است که این‌ها یک مقیاس موازی می‌سازند: تغییر `--text-body` هیچ اثری روی صفحه‌ای ندارد که `text-sm` نوشته، و همین باعث شد طرح صفحه‌ها با هم یکدست نباشد.

همین قاعده برای وزن هم برقرار است: نقل‌قول‌های `font-bold` روی `text-title` یا `text-display` ممنوع‌اند، چون آن پله‌ها عمداً روی وزن ۴۰۰ نشسته‌اند (بند ۵ پایین‌تر).

**چرا این مهم است:** پیش از این، لایهٔ کامپوننت‌های پایه (`src/components/ui/*`) حدود چهل پلهٔ خارج از مقیاس داشت (`text-sm` و `text-xs`). چون هر صفحه از همان کامپوننت‌ها ساخته می‌شود، این انحراف به‌طور خودکار به همهٔ صفحه‌ها ارث می‌رسید. اگر یک صفحه «با بقیه فرق دارد»، اول لایهٔ پایه را چک کن، نه آن صفحه را.

### چرا letter-spacing منفی حذف شده

Cursor متن‌های display را منفی ترک می‌کند (`-0.11px` تا `-2.16px`). این یک ترفند لاتین است — حروف بزرگ پهن را به هم می‌کشد — و در فارسی با letter joining که feature `calt` فونت انجام می‌دهد می‌جنگد. پس کپی نشد و حذف شده است.

فونت: `--font-sans` = `"IRANYekanX", Tahoma, system-ui, sans-serif` (خط 275) و `--font-mono` = `"Cascadia Mono", Consolas, "Courier New", monospace` (خط 276). فایل‌های فونت self-hosted در `frontend/public/fonts/IRANYekanXFaNumVF.woff2` و `.woff` هستند، با `font-weight: 100 1000` و `font-feature-settings: "kern" 1, "liga" 1, "calt" 1` (`src/styles.css` خطوط 23 تا 32). کلاس `.mono` برای شناسه‌های فنی LTR در متن RTL در خطوط 356 تا 360 تعریف شده است.

---

## ۴) هندسه و شعاع

تعریف‌شده در `@theme` فایل `src/styles.css` (خطوط 183 تا 185):

| توکن | مقدار | کاربرد دقیق |
| --- | --- | --- |
| `--radius-card` | `12px` | کارت و سطح صفحه (`components/ui/card.tsx:9`، `components/ui/surface.tsx:14`)، بنر، شیت، دیالوگ (`components/ui/dialog.tsx:62`)، قاب جدول داده (`components/ui/data-table.tsx:247`)، سایدبار شناور (`components/ui/sidebar.tsx:274`) |
| `--radius-control` | `8px` | همهٔ کنترل‌ها: دکمه در تمام اندازه‌ها (`components/ui/button.tsx:7,24,25,26,28`)، ورودی (`components/ui/input.tsx:10`)، آیتم منوی سایدبار، ردیف منوی فرمان، کادر حلقهٔ فوکوس (`src/styles.css:366`) |
| `--radius-xs` | `6px` | عناصر کوچک: کلیدهای `kbd` مثل «Esc» و «Ctrl K» (`components/ui/command-palette.tsx:131`)، دکمهٔ بستن دیالوگ، آیتم‌های منوی کشویی |
| pill (بدون توکن) | `rounded-full` | بج‌ها (`components/ui/badge.tsx:7`)، آواتار، نوار پیشرفت، نقطه‌های وضعیت. **توکنی به نام `--radius-pill` وجود ندارد**؛ pill یک کلاس Tailwind است |

نردبان قدیمی shadcn در `@theme inline` (خطوط 313 تا 317) از `--radius` ساخته می‌شود: `--radius-sm` = `calc(var(--radius) * 0.55)`، `--radius-md` = `calc(var(--radius) * 0.75)`، `--radius-lg` = `var(--radius)`، `--radius-xl` = `calc(var(--radius) * 1.25)`، `--radius-2xl` = `calc(var(--radius) * 1.6)`. این‌ها برای سازگاری shadcn باقی مانده‌اند و کلاس‌های `rounded-sm|md|lg|xl|2xl` در محصول ممنوع‌اند — `scripts/ui-audit.mjs` آن‌ها را به‌عنوان نقض توکن گزارش می‌کند.

فاصله‌های نام‌گذاری‌شدهٔ چگالی دادهٔ جدول در `:root` (خطوط 268 تا 270): `--density-row` = `44px`، `--density-cell-x` = `12px`، `--density-cell-y` = `10px`. توجه: این سه توکن در حال حاضر فقط اعلام شده‌اند و هیچ کامپوننتی آن‌ها را مصرف نمی‌کند؛ چگالی جدول فعلاً از prop `density` در `components/ui/data-table.tsx` (خطوط 82، 119، 177) کنترل می‌شود.

---

## ۵) ارتفاع، حرکت و فوکوس

### ارتفاع (Elevation) — فقط hairline

| توکن | مقدار | کاربرد |
| --- | --- | --- |
| `--shadow-card` | `none` | عمداً خالی. کارت‌ها عمق را از بوردر ۱ پیکسلی و کنتراست ink-on-cream می‌گیرند |
| `--shadow-raised` | `none` | عمداً خالی |
| `--shadow-pop` | `0 10px 28px rgba(38, 37, 30, 0.16), 0 2px 6px rgba(38, 37, 30, 0.07)` | **تنها سایهٔ واقعی محصول**. فقط برای overlay: دیالوگ (`components/ui/dialog.tsx:62`)، شیت (`components/ui/sheet.tsx:60`)، منوی کشویی (`components/ui/dropdown-menu.tsx:42,230`)، select (`components/ui/select.tsx:64`)، انتخاب بازهٔ تاریخ (`components/ui/date-range-picker.tsx:92`) |

منطق: یک overlay روی محتوای دلخواه شناور است و یک hairline تنها نمی‌تواند آن را جدا کند، پس `--shadow-pop` می‌ماند و به‌عنوان تنها ارتفاع محصول قیمت‌گذاری شده است.

هشدار فنی: توکن‌های `--shadow-*` عمداً در بلوک `@theme inline` تکرار **نشده‌اند** (توضیح در `src/styles.css` خطوط 319 تا 326). بازتعریف `--shadow-card: var(--shadow-card)` یک ارجاع دوری می‌سازد که به رشتهٔ خالی resolve می‌شود و همهٔ سایه‌های محصول را نامرئی می‌کند بدون اینکه خطایی بدهد. `--radius-card` نمونهٔ درست است: فقط در `@theme` اعلام می‌شود.

### حرکت (Motion)

| توکن | مقدار | کاربرد |
| --- | --- | --- |
| `--ease-out-standard` | `cubic-bezier(0.22, 1, 0.36, 1)` | منحنی استاندارد کل محصول |
| `--duration-fast` | `140ms` | تغییرات کوچک (رنگ، opacity) |
| `--duration-base` | `240ms` | انتقال‌های بزرگ‌تر |
| `--ease-standard` | `var(--ease-out-standard)` | نام مستعار صادرشده به Tailwind در `@theme inline` (خط 328) |

حرکت فقط بازخورد است، نه تزئین. کاهش حرکت در `src/styles.css` خطوط 370 تا 379 با `prefers-reduced-motion: reduce` اعمال می‌شود. `transition-all` در محصول ممنوع است (قاعدهٔ `motion-blanket` در `scripts/ui-audit.mjs`).

یک انیمیشن نام‌دار وجود دارد: `@utility animate-sweep` (خطوط 389 تا 391) با `@keyframes hive-sweep` (خطوط 393 تا 395) به مدت `1.4s` برای نوار پیشرفت نامعین در سطوح streaming و job.

### فوکوس (Focus)

| توکن | مقدار | کاربرد |
| --- | --- | --- |
| `--shadow-focus` | `0 0 0 1px var(--color-accent-400)` | هالهٔ باریک فوکوس، هم‌رنگ اکشن اصلی |
| `--shadow-focus-strong` | `0 0 0 3px rgb(245 78 0 / 0.16)` | هالهٔ پهن‌تر |
| `--ring` | `var(--color-accent-500)` | رنگ حلقهٔ فوکوس |

حلقهٔ سراسری در base layer (خطوط 363 تا 367): `:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; border-radius: var(--radius-control); }`.

چرا `--shadow-focus` در `@theme` و نه فقط در `:root`: ورودی‌های `--color-*` توسط `@theme` به Tailwind صادر می‌شوند ولی یک متغیر خام `:root` صادر نمی‌شود؛ inline کردن `var(--focus-border)` در یک utility مقدار خالی می‌دهد و حلقه بی‌صدا ناپدید می‌شود. برای همین `--color-shadow-focus` و `--color-shadow-focus-strong` در خطوط 195 تا 196 هم وجود دارند.

---

## ۶) قواعد ثابت (نباید تغییر کنند بدون تصمیم محصول)

این‌ها تصمیم محصول‌اند، نه جزئیات پیاده‌سازی. تغییرشان نیاز به تصمیم ثبت‌شدهٔ مالک محصول دارد.

1. **فقط حالت روشن (light mode only).** هیچ بلاک `.dark` و هیچ توکن تاریکی وجود ندارد. تصمیم محصول در `2026-08-17` و تأیید دوباره در `2026-09-13` (ثبت‌شده در `src/styles.css` خط ۴). `frontend/index.html` هم `<meta name="color-scheme" content="light" />` را اعلام می‌کند.
2. **RTL اجباری.** `<html lang="fa" dir="rtl">` در `frontend/index.html`. جهت هرگز نباید به LTR برگردد.
3. **فقط IRANYekanX.** فونت فارسی self-hosted در `frontend/public/fonts/`. فونت `CursorGothic` عمداً استفاده **نمی‌شود** (برخلاف سند Cursor که Inter را جایگزین مجاز می‌داند)؛ هر نقش CursorGothic با IRANYekanX در وزن معادل پر می‌شود و شرط اتصال حروف فارسی حفظ می‌گردد.
4. **حذف letter-spacing منفی.** ترکینگ منفی یک ترفند لاتین است و letter joining فارسی را خراب می‌کند. در پله‌های تایپ محصول اعمال نمی‌شود.
5. **وزن display و title برابر ۴۰۰.** «magazine voice»؛ جایگزین نمایش ۸۰۰ که محصول را شبیه قالب پیش‌فرض ادمین می‌کرد. heading و subheading روی ۶۰۰ می‌مانند.
6. **عمق فقط با hairline.** `--shadow-card` و `--shadow-raised` برابر `none` و باید همین‌طور بمانند. `--shadow-pop` تنها سایهٔ مجاز است و فقط برای overlay.
7. **اکسنت کم‌مصرف.** `#f54e00` فقط برای وردمارک، حلقهٔ فوکوس، نمودار/تزئین و نشان‌های سایدبار. برای هر اکشن متنی یا پرشدنی، `--primary` (اکسنت-۷۰۰) استفاده شود.
8. **بدون مشکی/سفید خالص در کف صفحه.** بوم `#f7f7f4` (کرم گرم) و ink `#26251e` (مشکی گرم) است، نه سفید و `#000`. همین دو مقدار باعث می‌شود محصول editorial بخواند و نه ادمین پیش‌فرض.
9. **هیچ مقدار inline در کامپوننت‌ها.** هر مقداری که کامپوننت لازم دارد باید از یک توکن در `src/styles.css` قابل دسترسی باشد؛ توکن جدید اول آنجا اضافه می‌شود (قاعدهٔ `[B4]` در `src/styles.css` خطوط ۱۲ تا ۱۳).

---

## ۷) نگاشت: هر تغییر کجا اعمال می‌شود

این جدول مهم‌ترین بخش برای یک ایجنت است: از قصد طراحی به توکن دقیق و محل دقیق ویرایش. شماره‌های خط مربوط به وضعیت فعلی `frontend/src/styles.css` است.

| قصد طراحی | توکن (یا فایل) | کجا ویرایش شود |
| --- | --- | --- |
| تغییر رنگ اکشن اصلی (مرحلهٔ خام) | `--color-accent-500` | `src/styles.css:78` |
| تغییر رنگ دکمهٔ اصلی و متن لینک | `--primary` | `src/styles.css:233` |
| تغییر رنگ متن روی دکمهٔ اصلی | `--primary-foreground` | `src/styles.css:234` |
| تغییر حالت hover دکمهٔ اصلی | `--primary-hover` | `src/styles.css:235` |
| تغییر رنگ دکمه/سطح ثانویه | `--secondary` و `--secondary-foreground` | `src/styles.css:236-237` |
| تغییر رنگ حالت انتخاب‌شده / هاور خنثی | `--accent` و `--accent-foreground` | `src/styles.css:238-239` |
| تغییر رنگ سطح غیرفعال و متن کم‌رنگ | `--muted` و `--muted-foreground` | `src/styles.css:240-241` |
| تغییر رنگ خطا/حذف (اکشن مخرب) | `--destructive` و `--destructive-foreground` | `src/styles.css:242-243` |
| تغییر رنگ متن/سطح/کادر خطا | `--color-error`، `--color-error-strong`، `--color-error-bg`، `--color-error-border` | `src/styles.css:101-104` |
| تغییر رنگ متن/سطح/کادر موفقیت | `--color-success*` | `src/styles.css:89-92` |
| تغییر رنگ متن/سطح/کادر هشدار | `--color-warning*` | `src/styles.css:93-96` |
| تغییر رنگ متن/سطح/کادر اطلاع | `--color-info*` | `src/styles.css:105-108` |
| تغییر ضخامت/رنگ hairline | `--border`، `--border-strong`، `--input` | `src/styles.css:244-246` |
| تغییر حلقهٔ فوکوس | `--ring`، `--shadow-focus`، `--shadow-focus-strong` | `src/styles.css:247,212,213` — حلقهٔ سراسری در `src/styles.css:363-367` |
| تغییر رنگ صفحه | `--background` (و `--color-neutral-50`) | `src/styles.css:218` و `src/styles.css:59` |
| تغییر رنگ متن اصلی | `--foreground` (و `--color-neutral-900`) | `src/styles.css:219` و `src/styles.css:68` |
| تغییر رنگ سطح کارت | `--card` | `src/styles.css:220` |
| تغییر رنگ سطح شناور | `--popover` | `src/styles.css:222` |
| تغییر رنگ سری‌های نمودار | `--chart-1` تا `--chart-5` | `src/styles.css:249-253` (رنگ‌های خام در `src/styles.css:112-125`) |
| تغییر رنگ‌های سایدبار | `--sidebar`، `--sidebar-foreground`، `--sidebar-primary`، `--sidebar-primary-foreground`، `--sidebar-accent`، `--sidebar-accent-foreground`، `--sidebar-border`، `--sidebar-ring` | `src/styles.css:255-262` |
| تغییر شعاع کارت‌ها و پنل‌ها | `--radius-card` | `src/styles.css:183` (و `--radius` در `src/styles.css:264`) |
| تغییر شعاع دکمه‌ها و ورودی‌ها | `--radius-control` | `src/styles.css:184` |
| تغییر شعاع عناصر ریز (kbd، آیتم منو) | `--radius-xs` | `src/styles.css:185` |
| تغییر شعاع بج/pill | `rounded-full` (توکن ندارد) | `src/components/ui/badge.tsx:7` |
| تغییر اندازهٔ فونت متن | `--text-body` | `src/styles.css:161` (line-height در `src/styles.css:162` و `src/styles.css:344`) |
| تغییر اندازهٔ فونت عنوان صفحه | `--text-title` | `src/styles.css:149-151` |
| تغییر اندازهٔ فونت هیرو/KPI | `--text-display` | `src/styles.css:145-147` |
| تغییر وزن عنوان بخش/کارت | `--text-heading--font-weight` | `src/styles.css:155` |
| تغییر وزن display | `--text-display--font-weight` | `src/styles.css:147` |
| تغییر متن کمکی و متادیتا | `--text-caption` و `--text-micro` | `src/styles.css:165-171` |
| تغییر فونت فارسی | `@font-face` و `--font-sans` | `src/styles.css:23-32` و `src/styles.css:275` (فایل‌ها در `public/fonts/`) |
| تغییر فونت شناسه‌های فنی | `--font-mono` و کلاس `.mono` | `src/styles.css:276` و `src/styles.css:356-360` |
| تغییر سایهٔ overlay | `--shadow-pop` | `src/styles.css:200` |
| خاموش/روشن کردن عمق کارت | `--shadow-card` و `--shadow-raised` | `src/styles.css:198-199` (هشدار: در `@theme inline` تکرار نشود) |
| تغییر سرعت انیمیشن | `--duration-fast` و `--duration-base` | `src/styles.css:204-205` |
| تغییر منحنی حرکت | `--ease-out-standard` | `src/styles.css:203` |
| تغییر انیمیشن نوار پیشرفت | `@utility animate-sweep` و `@keyframes hive-sweep` | `src/styles.css:389-395` |
| تغییر چگالی ردیف جدول | `--density-row`، `--density-cell-x`، `--density-cell-y` | `src/styles.css:268-270` (اعلام‌شده؛ مصرف در `src/components/ui/data-table.tsx`) |
| تغییر رنگ نوار اسکرول | `@utility scrollbar-thin` | `src/styles.css:383-386` |

فایل‌های کامپوننتی که توکن بالا را مصرف می‌کنند (برای بررسی اثر تغییر):

- دکمه: `src/components/ui/button.tsx`
- کارت و سطح: `src/components/ui/card.tsx`، `src/components/ui/surface.tsx`
- ورودی و فیلد: `src/components/ui/input.tsx`، `src/components/ui/field.tsx`
- بج و وضعیت: `src/components/ui/badge.tsx`، `src/components/ui/status-badge.tsx`، `src/lib/status.ts`
- جدول داده: `src/components/ui/data-table.tsx`، `src/components/ui/table.tsx`
- نمودار: `src/components/ui/chart.tsx`
- دیالوگ و شناورها: `src/components/ui/dialog.tsx`، `src/components/ui/dropdown-menu.tsx`، `src/components/ui/sheet.tsx`، `src/components/ui/select.tsx`
- پالت فرمان: `src/components/ui/command-palette.tsx`
- پوستهٔ اپ و سایدبار: `src/components/AppShell.tsx`، `src/components/ui/sidebar.tsx`
- بنر/هشدار: `src/components/ui/banner.tsx`، `src/components/ui/alert.tsx`
- کارت آماری: `src/components/ui/stat-card.tsx`

---

## پیوست: بررسی‌های خودکار مرتبط

- `npm run test:css` → `frontend/scripts/check-css-tokens.mjs` بررسی می‌کند که `shadow-card` به `none`، `shadow-raised` به `none`، `shadow-pop` به `0 10px 28px`، `shadow-focus` به `0 0 0 1px`، `rounded-card` به `12px`، `rounded-control` به `8px` و `rounded-xs` به `6px` resolve شوند و هیچ ارجاع دوری یا متغیر اعلام‌نشده‌ای وجود نداشته باشد.
- `npm run audit:ui` → `frontend/scripts/ui-audit.mjs` هشت قاعدهٔ فرار از توکن را می‌شمارد: `radius-adhoc`، `radius-legacy`، `shadow-legacy`، `shadow-adhoc`، `type-adhoc`، `weight-offscale`، `motion-blanket`، `color-raw`. آخرین اجرا: ۸۷ فایل، ۰ فرار.
