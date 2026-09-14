# AGENT WORKING STATE — hiveos code repo

> حافظه کاری عامل توسعه. هر سشن ابتدا این فایل + `hive/agent.md` + `hive/documentation/development-workflow.md` را بخوان.
> آخرین به‌روزرسانی: 2026-09-14 (پاس تعامل/چیدمان: ۴ باگ واقعی ریشه‌یابی و رفع شد — اسکرول کل سند، سایدبار کشیده، نبود هایلایت آیتم فعال، تاریخچهٔ چت غیرقابل‌دسترس در موبایل + بازگردانی اسکرول/سشن؛ e2e واقعی ۹/۹ + vitest ۹۶ + build/audit/budget سبز)
> (پاس یکدست‌سازی دیزاین‌سیستم: ۱۳۱ نقض توکن → ۰؛ ۳۰ فایل؛ گیت‌های build/tsc/vitest/a11y/budget سبز)
> (پاس دیباگ E: پنل ادمین زنده/رویدادها/سازمان‌ها + خطاهای فارسی و تلاش مجدد در فرانت + سخت‌سازی اسکنر/صف؛ 217 تست backend + 16 vitest + tsc/build سبز؛ مهاجرت‌ها تا 0023)

## پاس دیباگ 2026-09-12 (درخواست PO)

**دستور PO (ترجمه):** ۱) فایل خارج از فهرست قالب‌ها در پویش رد شود ۲) `frontend/dist.tar.gz` فایل من نیست (حذف شد) ۳) بعد از آماده‌شدن نسخهٔ ایمن، برو سراغ سرور؛ سرور باید تمیز و مرتب باشد ۴) در پنل ادمین وضعیت لحظه‌ای سرور در پارامترهای کلیدی ۵) لاگ‌ها به پنل ادمین اضافه شود ۶) سازمان‌های ثبت‌نام‌کرده + عملیات مرتبط با آن‌ها ۷) در فرانت خطاها نمایش داده نمی‌شدند یا انگلیسی/نامناسب بودند — خطا با متن توضیحی فارسی ۸) دکمه‌های بازگشت/تلاش مجدد در فرایندهایی که لازم است.

**زیرساخت/سرور — مهم:** استیجینگ ساعتی حساب می‌شود؛ تا وقتی PO صریحاً نگوید «برو سرور» هیچ کانتینری را بالا نیاور، دیپلوی/rollback نزن و فایل روی سرور را تغییر نده. دیدن وضعیت (read-only از طریق SSH) مجاز است.

1. **پویش پوشه = همان جدول قالب US-205** (`knowledge/service.py`): فایل با پسوند خارج از فهرست (مثل `.bin`/`.zip`/`.html`) در پویش نادیده گرفته می‌شود؛ تست‌های مربوطه به‌روزرسانی شدند.
2. **پنل ادمین — وضعیت لحظه‌ای** (`GET /admin/system-status`): `health` سه‌حالته، شمارنده‌های زندهٔ DB در یک کوئری، صف پردازش به‌تفکیک وضعیت، حجم/اتصال DB، تأخیر، head مایگریشن + مقایسه با هد فایل‌ها، uptime/pid/thread، دیسک و بار میزبان، آخرین رویداد. UI هر ۱۰ ثانیه خودکار refresh می‌کند.
3. **پنل ادمین — رویدادها** (`GET /admin/logs`): `audit_logs` + نام سازمان/کاربر، فیلتر all/activity/error، جستجو، صفحه‌بندی، و بازهٔ اختیاری دنبالهٔ فایل لاگ سرور (`LOG_FILE`).
4. **پنل ادمین — سازمان‌ها + عملیات مرتبط** (`GET /admin/organizations/{id}`): فهرست سازمان‌ها با کاربران/اسناد/گفتگو/اجرا/آخرین فعالیت؛ جزئیات شامل اعضا، تراکنش‌های کیف پول، درخواست‌های شارژ، رخدادهای اخیر، وضعیت اسناد و پوشهٔ دانش. عمل «افزودن اعتبار» با تأیید صریح (`window.confirm`).
5. **فارسی‌سازی خطاها** (`frontend/src/api/errors.ts`): نقشهٔ کد خطا → جملهٔ توضیحی فارسی + fallback بر اساس HTTP status؛ `api/client.ts` همهٔ خطاها (شبکه، timeout، پاسخ نامعتبر) را از همین مسیر می‌فرستد. پیام توسعه‌دهندهٔ انگلیسی سرور هرگز در UI دیده نمی‌شود (تست رگرسیون در `Chat.test.tsx`).
6. **تلاش مجدد/بازگشت**: کامپوننت `RetryNotice` + دکمهٔ «تلاش مجدد» در Chat/Knowledge/Wallet/Subscription و تب‌های پنل ادمین؛ «بازگشت» در مراحل ثبت‌نام (سازمان ← حساب مدیر ← کد تأیید).
7. **رفع باگ‌های واقعی ضمن پاس**: طوفان NUL از فایل متنی آلوده به DB (`_extract_text_file`)، نشت handle در `os.walk` اسکنر، نام‌گذاری`updated_at` منقضی در retry صف، لیستِ بدون سقف حافظهٔ بافر SSE، 429 سرریز از تست‌های قبلی روی لیمیتر ادمین.
8. **گیت‌ها (2026-09-12)**: `pytest` **217 passed**؛ `ruff check .` سبز؛ `npm run build` (tsc+vite) سبز؛ `vitest` **16 passed**. تست‌های جدید: `tests/test_admin_ops_api.py` (۳) + `tests/test_hardening_fixes.py` (۸). UI محلی: `http://127.0.0.1:8080` (پنل: `/admin`).
9. **استقرار روی استیجینگ انجام شد (2026-09-12)** — سرور `hiveos-staging` (193.93.169.136):
   - تصویر `hiveos/api:secure-20260912` از درخت فعلی ساخته، منتقل و بالا آمد؛ SPA جدید (`index-CVcC8xVa.js`) هم در `/var/www/hiveos/dist` نصب شد.
   - مهاجرت‌ها تأیید شد: `alembic_version=0023` و ۲۷ جدول در اسکیمای `hiveos`. خطای قبلی `UndefinedTableError` مربوط به یک کانتینر موقت روی دیتابیس نادرست بود، نه اسکیمای خراب.
   - **سموم e2e با مسیر واقعی کاربر:** ساخت سازمان → ثبت مالک → `workspaces/initialize` → `brain/initialize` → کیف پول ۵۰ اعتبار خوش‌آمد؛ سپس خواندن همان داده در پنل ادمین (فهرست سازمان‌ها، جزئیات سازمان، رویدادها، `system-status`، `logs`). پاسخ ۴۰۴ برای UUID ناشناس هم درست بود. پس از تست همهٔ ردیف‌های آزمون از DB پاک شدند (orgs=0, users=0, wallets=0, audit=0).
   - **تمیزکاری سرور:** `dist_old`، `hiveos-api.tgz`/`hiveos-deploy.tgz` در `/home/ubuntu/deploy`، سه تصویر قدیمی docker (از جمله `staging-0e01c84` سه‌گیگابایتی)، کش apt و ژورنال قدیمی حذف شدند. دیسک از ۴۸٪ به **۳۱٪** (7.2G/24G) رسید. تصویر فعلی + یک تصویر rollback نگه داشته شدند.
   - **نصب‌کنندهٔ ویندوز** با آدرس `https://hivesystem.ir/` بازساخته و در `/var/www/hiveos/downloads/HiveOS-Setup-0.1.0.exe` جایگزین شد.
   - **دامنه/تی‌ال‌اس:** `hivesystem.ir` اکنون از طریق Cloudflare به همین سرور می‌رسد؛ `https://hivesystem.ir/api/health` و `/` و `/admin` همه ۲۰۰ و گواهی Let's Encrypt معتبر است (اجرای certbot روی سرور لازم نشد).
   - امنیت: ufw فعال، `passwordauthentication no`، root فقط با کلید، `unattended-upgrades` فعال، `secrets/` و `.env` با مجوز ۶۰۰ و مالک root. **پورت ۸۰۸۰ هنوز در ufw باز است ولی سرویسی روی آن گوش نمی‌دهد — بستن آن منتظر تأیید PO است.**

## پاس تطبیق با اصول طراحی (۱۱۴ مقاله) — 2026-09-14

**درخواست PO:** دو فایل فهرست لینک مقاله در `design article/` (UX Pilot ۶۳ + Pencil & Paper ۵۱)؛ هر لینک مطالعه و اصولش با HiveOS تطبیق داده شود، شکاف‌ها اصلاح شوند.

**روش:** ۵ ساب‌ایجنت موازی، هرکدام یک دسته مقاله را fetch و به اصول «قابل‌سنجش» تبدیل کرد؛ خروجی در `design article/_findings/batch{1..5}-*.md` (۲۲۲ اصل). **محدودیت مهم: `pencilandpaper.io` برای fetcher ما 403 Cloudflare می‌دهد** — تقریباً نیمی از لینک‌های آن دامنه استخراج نشدند و این در فایل‌ها صادقانه علامت خورده (هیچ محتوایی جعل نشد). اصول به‌دست‌آمده از `uxpilot.ai` (۲۰۰) کافی بود.

**نکتهٔ روش‌شناسی:** دو «باگ» اولیه (کرش پنل ادمین) با استاب ناقص خودم ساخته شده بودند، نه محصول — با استاب واقعی (`db`/`jobs`/`counters`/`uptime`) رد شدند. همچنین محاسبهٔ دستی کنتراست من اشتباه بود؛ **axe-core مرجع است**، نه ریاضی خودم.

**اصلاحات انجام‌شده (هم روی سامانه اصلی هم پنل ادمین، طبق تأکید PO):**

1. **landmark تودرتو در هر ۱۱ مسیر** — `SidebarInset` یک `<main>` رندر می‌کرد و داخلش `<main>` دوم بود (`landmark-main-is-top-level`، `landmark-no-duplicate-main`, `landmark-unique`). حالا `SidebarInset` یک `<div>` است و `<main>` داخلی نقش landmark را نگه می‌دارد.
2. **۹ لینک ناوبری بیرون از هر landmark** (`region`، ۹ گره در هر مسیر) — سایدبار دسکتاپ `<div>` بود؛ حالا `<nav aria-label="ناوبری اصلی">` (هر دو شاخهٔ `collapsible`).
3. **`aria-controls` معلق (critical)** — Knowledge از `Tabs` به‌عنوان *فیلتر* استفاده می‌کرد: ۵ تریگر بدون هیچ `TabsContent`، پس همه به عناصر ناموجود اشاره می‌کردند. به `role="group"` + `aria-pressed` تبدیل شد — همان الگویی که Wallet و EventsView از قبل دارند.
4. **progressbar بی‌نام** (`aria-progressbar-name`، serious) — `<Progress>` در Usage؛ `aria-label` اضافه شد.
5. **`page-has-heading-one`** — حالت‌های بارگذاری/خطای Subscription و کل صفحهٔ Chat `<h1>` نداشتند؛ اضافه شد (Chat با `sr-only` چون کل صفحه محتواست).
6. **`heading-order`** — در Knowledge از h1 به h3 می‌پرید؛ h2 شد.
7. **`empty-table-header`** — ستون اقدام `<th>` خالی بود؛ `<span class="sr-only">اقدام`.
8. **ErrorBoundary بدون landmark** — وقتی خطا رخ می‌دهد، `<main>` پوسته را با خود می‌برد؛ حالا خودش `<main>` است تا دکمه‌های بازیابی در landmark باشند.
9. **۸ رشتهٔ a11y انگلیسی در محصول کاملاً فارسی** — `Close`×۲، `Toggle Sidebar`×۳، `Loading`، `More`، `breadcrumb`؛ همه فارسی شدند (کاربر screen-reader فارسی این‌ها را می‌شنید).
10. **باگ‌های پاس قبل** (هایلایت منو، ارتفاع پوسته، تاریخچهٔ موبایل، بازگردانی اسکرول) — همه با پروب مرورگر تأیید و در همین پاس نگه داشته شدند.

**نتیجهٔ axe: از ۴ ایراد critical/serious + ۳۰ moderate در ۱۱ مسیر → صفر در هر ۱۲ مسیر.**
**تست رگرسیون دائمی:** `frontend/e2e/a11y.spec.ts` (۱۲ تست axe روی build واقعی). در jsdom دیده نمی‌شود چون layout ندارد.

**گیت‌ها:** `ui-audit` ۰ · `build` سبز · `vitest` ۱۸/۹۶ · `playwright` **۲۲/۲۲** (۹ موجود + ۱۲ a11y + ۱) · `check-css-tokens` · `check-bundle-budget` در بودجه. بک‌اند دست‌نخورده.

**باقی‌ماندهٔ نامنطبق (اصل اثبات‌شده، بدون اصلاح):** ذخیرهٔ کوئری فیلتر، pin/favorite مسیرها، density switcher جدول، ستون‌های چسبان جدول، undo برای اقدامات برگشت‌پذیر، تست screen-reader واقعی (NVDA/JAWS) — هیچ‌کدام الان در محصول نیستند و افزودنشان کار محصولی است نه اصلاح.

## پاس تعامل و چیدمان — 2026-09-14 (درخواست PO: هایلایت منو، دکمه بازگشت، حفظ اسکرول/وضعیت چت، ریسپانسیو، فاصلهٔ خالی بین تاریخچه‌ها)

**روش:** به‌جای حدس از روی خواندن کد، فرضیه‌ها با پروب واقعی مرورگر (Playwright روی build واقعی، API استاب‌شده در لایه شبکه) اندازه‌گیری شدند. همین کار باعث شد دو مورد «باگ» که اول پیدا شدند به‌عنوان خطای خود پروب کنار گذاشته شوند، و چهار باگ واقعی با شاهد عددی تأیید شوند.

1. **ریشهٔ اصلی — ارتفاع پوسته (`sidebar.tsx` + `AppShell.tsx`):** `SidebarProvider className="min-h-dvh"` فقط «حداقل» ارتفاع می‌دهد، پس پوسته به ارتفاع محتوا رشد می‌کرد. اندازه‌گیری: `documentScrolls=true` (scrollHeight 5671 در برابر clientHeight 720)، اسکرولر داخلی ترنسکریپت هرگز فعال نمی‌شد (clientHeight === scrollHeight === 5475)، و سایدبار به‌عنوان آیتم کنارِ فلکس به ۵۶۱۵px کشیده و از دید خارج می‌شد (`asideTop=-4895`). رفع: `h-svh min-h-0` روی provider، `min-h-0` روی `<main flush>`، `shrink-0` روی فوتر. نتیجه: `documentScrolls=false`، `scrollerScrolls=true` (clientH 525)، `asideTop=56`. **همین باگ عیناً در پنل ادمین هم بود** (`AdminApp`) و با `h-svh min-h-0` + `overflow-y-auto` روی `<main>` رفع شد.
2. **هایلایت آیتم فعال منو (هر دو پوسته):** `SidebarMenuButton` مقدار `data-active={isActive}` را با پیش‌فرض `false` هاردکد می‌کند و چون داخل `asChild`/`Slot` است، مقدار فرزند (`NavLink`) را بازنویسی می‌کند؛ ضمناً `NavLink` اصلاً `data-active` نمی‌سازد (React Router `aria-current` می‌گذارد). پس قاعدهٔ `data-[active=true]:bg-sidebar-accent` هرگز فعال نمی‌شد. رفع: محاسبهٔ `isActive` در `AppShell` و `AdminApp` و پاس‌دادن آن به پراپ. اندازه‌گیری: از `active:"false"` و پس‌زمینهٔ شفاف به `active:"true"` و `rgb(238,241,251)`.
3. **تاریخچهٔ چت در موبایل:** ریل `hidden … md:flex` بود و هیچ معادلی نداشت، پس زیر ۷۶۸px کل تاریخچه غیرقابل‌دسترس بود. رفع: همان ریل در یک تابع رندر مشترک، یک‌بار به‌صورت ستون دسکتاپ و یک‌بار داخل `Dialog` زیر md (focus trap/Escape با Radix) + دکمهٔ «گفتگوها» و «بازگشت» در نوار موبایل. با کلیک روی هر گفتگو دیالوگ بسته می‌شود.
4. **حفظ وضعیت چت:** `sessionStorage` (`hiveos.chat.view`) هم سشن باز و هم آفست اسکرول را نگه می‌دارد. دو تلهٔ واقعی که با تایم‌لاین پروب پیدا شد: (الف) `scrollIntoView` نرم با هر remount دوباره شلیک می‌شد و ریستور را می‌کشید پایین — با `followRef` فقط ارسال پیام خود کاربر اسکرول را حرکت می‌دهد؛ (ب) هنگام teardown مسیر، اسکرولر جمع می‌شد و مرورگر `scrollTop` را صفر می‌کرد و همان رویداد مقدار ذخیره‌شده را با ۰ بازنویسی می‌کرد — با نادیده‌گرفتن رویداد اسکرول روی پنل جدا/صفر‌ارتفاع رفع شد. نتیجه: ۵۰۰ → ۵۰۰ (`preserved:true`).
5. **ریسپانسیو و تارگت لمسی:** در عرض‌های ۳۲۰/۳۷۵/۷۶۸/۱۰۲۴/۱۴۴۰ روی ۵ مسیر، **صفر سرریز افقی**. کنترل‌های زیر حد ۴۴px اصلاح شدند: `SidebarTrigger` (۲۸px → `size-11 md:size-7`)، دکمه‌های صفحه‌بندی Wallet/Knowledge (`size="xs"` ۲۴px → `sm`)، دکمهٔ «کپی پیام» (`min-h-11 md:min-h-0`). نتیجه: `smallTargets: []`.
6. **ایراد پنهان پنل ادمین:** `OverviewView` دو جا `data.jobs.open` را بدون گارد می‌خواند (خط ۳۶ و ۶۸) درحالی‌که هر جای دیگر `?? 0` دارد؛ پاسخ ناقص `/system-status` کل صفحهٔ فرود پنل را از طریق ErrorBoundary می‌انداخت. گارد اضافه شد.
7. **تست:** `Chat.test.tsx` شش‌تایی شکست چون `useNavigate` اضافه شد و تست بدون Router رندر می‌کرد؛ به `renderWithRouter` (هلپر موجود در `src/test/render.tsx`) منتقل شد. **نکتهٔ مهم برای پاس بعدی: هیچ فایل تست فارسی را با `Set-Content`/`Get-Content -Raw` بازنویسی نکنید** — در همین پاس تلاش شد و پرونده فقط چون ابزار `edit` جلویش را گرفت سالم ماند (بررسی شد: mojibake=0، ۱۹۵ کاراکتر فارسی).
8. **گیت‌ها:** `ui-audit` ۰ نقض · `npm run build` (tsc+vite) سبز · `vitest` **۱۸ فایل / ۹۶ تست** · `playwright e2e` **۹/۹** روی build واقعی · `check-css-tokens` ۷ توکن · `check-bundle-budget` در بودجه. بک‌اند دست‌نخورده.

## پاس یکدست‌سازی دیزاین‌سیستم — 2026-09-14 (درخواست PO: «نسبت به UI حس حرفه‌ای بودن ندارم»)

**تشخیص (شواهد از کد، نه سلیقه):** UI چهار زبان بصری همزمان داشت، همه در لایهٔ توکن — نه در پالت:
سه نردبان شعاع موازی (معنایی ۶/۹/۱۴ + shadcn کسری ۷.۷/۱۰.۵/۱۴/۱۷.۵/۲۲.۴ + ۳۶ عدد دستی)،
۹ سایهٔ خام shadcn که سه سطح توکن را دور می‌زد، ۲۸ وزن ۸۰۰ بیرون از نردبان ۴۰۰/۵۰۰/۶۰۰/۷۰۰،
و ۵ `transition-all` بی‌توکن motion. سند کرسر **کپی نشد** — پالت/تایپوگرافی آن آنتاگونیست برند HiveOS است
(کرم گرم/نارنجی/وزن ۴۰۰ در برابر سرمه‌ای/وزن ۷۰۰)؛ فقط اصل «یک نردبان، بدون مقدار دستی» گرفته شد.

1. **ابزار گیت** — `frontend/scripts/ui-audit.mjs` (جدید): ۸ قاعده (radius-adhoc، radius-legacy، shadow-legacy، shadow-adhoc، type-adhoc، weight-offscale، motion-blanket، color-raw)، هر یافته با فایل+خط، `--json` برای مصرف ماشینی، exit code غیرصفر هنگام نقض. الگوی «هر ایراد شاهد خط‌دار دارد» از `ui-defect-register` به خود دیزاین‌سیستم تعمیم داده شد.
2. **نتیجه:** `131 token bypasses → 0`. ۳۰ فایل `src` تغییر کرد: ۳۶ شعاع دستی → `rounded-xs|control|card`، ۴۳ شعاع ارثی shadcn → همان نردبان، ۹+۱۰ سایه → `shadow-card|raised|pop`، ۲۸ `font-extrabold`/`font-black` → `font-bold`، ۵ `transition-all` → نام‌دار.
3. **باگ واقعی که ضمن کار پیدا شد:** توکن `--focus-border` در `RegisterOrganization.tsx` داخل `shadow-[0_0_0_1px_var(--focus-border)]` **هرگز رندر نمی‌شد** — `@theme` فقط کلیدهای `--color-*` را به Tailwind export می‌کند و متغیر برهنهٔ `:root` در مقدار utility خالی می‌شود. دو توکن `--shadow-focus`/`--shadow-focus-strong` اضافه و همان‌جا (و در `sidebar.tsx`) جایگزین شد؛ در CSS ساخته‌شده تأیید شد.
4. **گیت‌ها:** `npm run build` (tsc+vite) سبز · `vitest` **18 فایل / 96 تست** سبز (شامل `a11y.test.tsx`) · `check-bundle-budget.mjs` در بودجه (entry gzip ۱۴۹.۹/۱۹۰KB، css ۱۴.۴/۳۰KB). بک‌اند دست‌نخورده.
4b. **باگ دوم — کل ارتفاع رابط رندر نمی‌شد (کشف و رفع شد):** `@theme` سه سایهٔ واقعی را تعریف می‌کرد و بعد `@theme inline` دوباره `--shadow-card: var(--shadow-card)` را می‌نوشت. Tailwind آن را بازتعریف می‌گیرد، مقدار واقعی `@theme` حذف می‌شود و ارجاع **حلقه‌ای** می‌ماند. `var()` حلقه‌ای در CSS **رشتهٔ خالی** می‌دهد، نه خطا: کلاس کامپایل می‌شد، audit توکن را «سالم» می‌دید، ولی `box-shadow: none` رندر می‌شد. یعنی همهٔ `shadow-card/raised/pop` (کارت‌های آماری، پنل اعتبار کیف پول، دکمهٔ ورود، سایدبار شناور) **بی‌سایه** بودند. اندازه‌گیری قبل: `getComputedStyle` = `none` و `--shadow-card` = `""`. بعد: مقادیر واقعی. `--radius-card` هرگز تکرار نشده بود و همیشه کار می‌کرد — همان الگوی درست.
4c. **گیت جدید `frontend/scripts/check-css-tokens.mjs`:** استایل ساخته‌شده را می‌خواند، `var()` را تا مقدار نهایی دنبال می‌کند (پس `rounded-card → var(--radius-card) → 14px` سالم است) و روی ارجاع حلقه‌ای یا متغیر اعلام‌نشده fail می‌دهد. با بازگرداندن عمدی همان باگ آزموده شد: exit ۱ و نام‌بردن چرخه.
4d. **`ui-audit.mjs` به CI وصل شد** — پاس قبلی آن را ساخته بود ولی هیچ workflowی صدایش نمی‌زد، پس «۰ نقض» هیچ‌وقت enforce نمی‌شد و ۱۳۱ اصلاح می‌توانست ذره‌ذره برگردد. هر دو گیت الان در job فرانت هستند.
5. **هشدار عملیاتی برای پاس‌های بعدی:** هرگز فایل‌های `src` فارسی را با `Get-Content -Raw` + `WriteAllText` بازنویسی نکنید — PowerShell آن‌ها را cp1252 می‌خواند و UTF-8 می‌نویسد و تمام متن فارسی به mojibake تبدیل می‌شود (در همین پاس ۶ فایل خراب شد و با جدول معکوس cp1252 ترمیم شد؛ `git checkout` امن نبود چون WIP قبلی PO را پاک می‌کرد). ویرایش باید از طریق ابزار `edit` یا Node با `utf8` باشد.
6. **فازبندی باقی‌مانده (انجام نشده، منتظر تصمیم PO):** پنل ادمین هنوز ۲۶ `<button>` و ۷ `<input>` خام دارد و تقریباً از `ui/select.tsx` استفاده نمی‌کند؛ `aria-live` فقط ۳ مورد؛ `text-body`/`text-title` سهم کم (۱۱/۱۰) در برابر `micro`/`caption` (۹۰/۱۳۱) یعنی سلسله‌مراتب صفحه‌ای نازک است.

## وضعیت فعلی (دستور PO: «هیچ چیز بازی نماند؛ من فقط در پنل ادمین ست می‌کنم»)

7. **رفع یافته‌های ریویو خارجی v0.1** (`00ae41d`): B1–B7 / H1–H3 / S1–S13 بسته شدند — جلسات ادمین در DB (`admin_sessions`، 0021)، fail-fast اعتبارات پیش‌فرض در non-dev، کیف پول اتمیک + UNIQUE(org)، resolve مسیر انجمستون، اسکیمای settings، OTP ثابت‌زمان، binding/مرز SSE + TTL/cap، partial unique index اسکن (0022). رگرسیون: `tests/test_review_remediation.py` (8 تست). گزارش: `hive/reports/tasks/2026-09-11-review-remediation.md`.
8. **منده‌های PO**: T-S5-4 (تأیید صریح حضور محصول)، provisioning سرور استیج، کلید‌ها/پلن‌های پنل، محتوای لندینگ، دامنه.
9. **استیجینگ مستقر** (2026-09-11): `hiveos-staging` 193.93.169.136 — DB کانتینر + api `hiveos/api:staging-0e01c84` + nginx هاست (SPA+proxy)؛ 27 جدول، سموک پنل (login/logout/revoke) سبز. جزئیات: `hive/reports/tasks/2026-09-11-staging-server-deploy.md`. TLS + دامنه موکول PO.
10. **سرور استیجینگ خاموش شد** (تصمیم PO، 2026-09-11): تست‌ها موقتا لوکال — UI `http://127.0.0.1:8080`، اجرا: دسکتاپ `HiveOS-Local.bat` یا `hiveos/start-local.ps1`. وضع سرور هنگام خاموش‌سازی: api `staging-0e01c84` Up، db healthy، 27 جدول، پورت 80 توسط هاستینگ باز شد، certbot 2.9 نصب، `server_name hivesystem.ir` ست، nginx روی 80/8080/2052+alt.
11. **موانع هنوز باز (برای بازگشت به سرور)**: (a) DNS `hivesystem.ir` هنوز به edge اروان (185.143.234.x) اشاره می‌کند و edge به origin 502 می‌دهد — راهحل: A record → 193.93.169.136 یا درست کردن origin در پنل اروان (اکانت درست)؛ (b) بعد از DNS: `certbot --nginx -d hivesystem.ir`؛ (c) rebuild اپ ویندوزی با `https://hivesystem.ir` + آپلود دوباره.
12. **رفع نظارات بازبینی نهایی** (2026-09-11، شاخه `task/review-final-remediation`): بازبینی نهایی (`2026-09-11-final-review.md`) ۷ مورد خواست — همگی بسته شدند:
    - **R1** چهار endpoint ادمین (`_read_setting`/`put_setting`/`admin_credit_op`/`system_status`) → `_shared_engine()`؛ dispose حذف.
    - **R2** `__import__("json")` → `import json`.
    - **R3** `get_or_create_wallet` → IntegrityError → rollback + re-select.
    - **R4** اعتبار ادمین → `updated_at=func.now()`.
    - **R5** تست → `await dispose` (خطای ناپایدار teardown ریشه‌یابی و رفع شد).
    - **NB-1** rate-limit پشت proxy → `ProxyHeadersMiddleware` + `trust_proxy_xff` + `client_key` از XFF + `TRUSTED_PROXIES` env (compose/.env) + `X-Forwarded-Proto` در nginx و `serve_ui.py`.
    - **NB-2** race register_owner → `FOR UPDATE` + partial unique index `uq_organizations_owner_user_id` (مهاجرت 0023، برگشت‌پذیر).
    - گیت‌ها: ruff سبز؛ pytest **206 passed** ×3 پیاپی (۴ رگرسیون جدید)؛ alembic head 0023 (downgrade↔upgrade سبز)؛ tsc/vitest سبز. گزارش‌ها به‌روز شدند. **merge به main منتظر تأیید صریح PO.**

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

## تله‌ی عملیاتی ثبت‌شده (2026-09-13) — دو فایل compose با نام یکسان

هنگام افزودن mount پشتیبان، فایل `deploy/docker-compose.staging.yml` روی سرور کپی شد،
در حالی که استک واقعی staging با `infrastructure/docker-compose.staging.yml` بالا می‌آید:

- `infrastructure/docker-compose.staging.yml` → **فایل واقعی روی سرور** (project `hiveos-app`،
  پورت `127.0.0.1:8100:8100`، external network `hiveos_default`، mount های
  `/opt/hiveos/storage` و `/opt/hiveos/ingestion` و `/opt/models`، env از `/opt/hiveos/app/.env`).
- `deploy/docker-compose.staging.yml` → استک کامل با سرویس داخلی `db` و nginx کانتینری؛
  **روی سرور استفاده نمی‌شود** و کپی‌کردنش mount ها و پورت را از بین می‌برد.

فایل اشتباه روی سرور کپی شده بود؛ بلافاصله از `infrastructure/` بازگردانی شد و استک بدون
قطعی سرویس سالم ماند (هر دو health داخلی و عمومی 200). درس: قبل از هر `cp` روی فایل
کانفیگ سرور، اول محتوای فعلی همان فایل خوانده شود.

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