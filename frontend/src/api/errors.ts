// Persian user-facing text for every API error code (PO request 2026-09-12).
//
// The API answers with a stable machine code plus an English developer message.
// The panel must never show that English string: this map is the single place
// where a code becomes a sentence a Persian-speaking owner can act on. An
// unmapped code falls back to a neutral Persian sentence (never to English).

const MESSAGES: Record<string, string> = {
  // --- session / access -----------------------------------------------------
  AUTH_REQUIRED: "برای ادامه باید وارد حساب خود شوید.",
  SESSION_EXPIRED: "نشست شما منقضی شده است؛ دوباره وارد شوید.",
  SESSION_REVOKED: "این نشست بسته شده است؛ دوباره وارد شوید.",
  SESSION_NOT_ACTIVE: "این نشست فعال نیست؛ دوباره وارد شوید.",
  AUTH_INVALID_CREDENTIALS: "نام کاربری یا رمز عبور درست نیست.",
  INVALID_CREDENTIALS: "نام کاربری یا رمز عبور درست نیست.",
  ACCOUNT_LOCKED: "ورود موقتاً قفل شده است. چند دقیقه بعد دوباره تلاش کنید.",
  UNAUTHORIZED: "اجازهٔ دسترسی به این بخش را ندارید.",
  FORBIDDEN: "اجازهٔ دسترسی به این بخش را ندارید.",
  ADMIN_FORBIDDEN: "نشست مدیر سامانه معتبر نیست؛ دوباره وارد شوید.",
  NO_ORGANIZATION: "سازمانی برای این حساب ثبت نشده است.",
  ORGANIZATION_NOT_FOUND: "سازمان موردنظر پیدا نشد.",
  NOT_FOUND: "مورد درخواستی پیدا نشد؛ ممکن است حذف شده باشد.",
  RATE_LIMITED: "تعداد درخواست‌ها زیاد بود؛ چند لحظه بعد دوباره تلاش کنید.",

  // --- registration / owner / OTP -------------------------------------------
  PASSWORD_MISMATCH: "تکرار رمز عبور با رمز عبور یکسان نیست.",
  MOBILE_ALREADY_VERIFIED: "این شمارهٔ موبایل قبلاً تأیید شده است.",
  OTP_INVALID: "کد تأیید درست نیست؛ دوباره وارد کنید.",
  OTP_EXPIRED: "کد تأیید منقضی شده است؛ کد جدید بگیرید.",
  OTP_LOCKED: "تلاش‌های ناموفق زیاد بود؛ کد جدید بگیرید.",
  OWNER_ALREADY_EXISTS: "حساب مدیر برای این سازمان قبلاً ساخته شده است.",
  CANNOT_DELETE_OWNER: "حساب مالک سازمان را نمی‌توان حذف کرد؛ به‌جای آن کل سازمان را حذف کنید.",
  PASSWORD_POLICY: "گذرواژه باید حداقل ۸ نویسه و شامل حرف و رقم باشد.",
  OTP_COOLDOWN: "کد تأیید تازه فرستاده شده است؛ کمی بعد دوباره درخواست کنید.",
  SMS_DELIVERY_FAILED: "ارسال پیامک ناموفق بود؛ کمی بعد دوباره تلاش کنید.",
  USERNAME_TAKEN: "این نام کاربری قبلاً انتخاب شده است.",
  USERNAME_AVAILABLE: "این نام کاربری در دسترس است.",

  // --- onboarding / workspace / brain ---------------------------------------
  WORKSPACE_NOT_FOUND: "فضای کاری این سازمان ساخته نشده است.",
  BRAIN_WORKSPACE_NOT_READY: "فضای کاری هنوز آماده نشده است؛ چند لحظه بعد دوباره تلاش کنید.",
  BRAIN_INITIALIZATION_FAILED: "راه‌اندازی هستهٔ دانش ناموفق بود؛ یک‌بار دیگر تلاش کنید.",
  KNOWLEDGE_BRAIN_NOT_READY: "ابتدا مراحل قبلی راه‌اندازی را کامل کنید.",
  INGESTION_PATH_REQUIRED: "ابتدا پوشه اسناد را انتخاب کنید.",
  // These three belong to the on-prem "server folder" variant. In the cloud
  // client the folder is on the owner's own PC, so the text must not tell the
  // owner to go fix a path on a server they never see.
  INGESTION_PATH_NOT_ABSOLUTE:
    "نشانی این پوشه کامل نیست. با دکمهٔ «انتخاب پوشه» مسیر درست را انتخاب کنید (مثلاً C:\\Documents).",
  INGESTION_PATH_NOT_ALLOWED: "این مسیر خارج از محدودهٔ مجاز سامانه است.",
  INGESTION_PATH_NOT_FOUND: "این پوشه پیدا نشد؛ ممکن است جابه‌جا یا حذف شده باشد.",
  INGESTION_PATH_NOT_READABLE: "این پوشه قابل خواندن نیست؛ سطح دسترسی آن را بررسی کنید.",
  INGESTION_PATH_TOO_LONG: "نشانی این پوشه بسیار بلند است؛ پوشهٔ نزدیک‌تری انتخاب کنید.",
  MANIFEST_TOO_LARGE: "تعداد فایل‌های این پوشه بیشتر از حد مجاز است؛ پوشهٔ کوچک‌تری انتخاب کنید.",
  SCAN_ALREADY_RUNNING: "پویش این پوشه از قبل در حال اجراست.",
  SOURCE_DISABLED: "منبع دانش غیرفعال است؛ ابتدا آن را فعال کنید.",

  // --- knowledge / upload ---------------------------------------------------
  KNOWLEDGE_SOURCE_NOT_FOUND: "پوشهٔ اسناد این سازمان ثبت نشده است.",
  WORKSPACE_INITIALIZATION_FAILED: "ساخت فضای کاری ناموفق بود؛ یک‌بار دیگر تلاش کنید.",
  KNOWLEDGE_ASSET_NOT_FOUND: "سند موردنظر پیدا نشد.",
  FOLDER_ASSET_NOT_DELETABLE: "اسناد پوشه از این صفحه قابل حذف نیستند.",
  UPLOAD_EMPTY: "هیچ فایلی انتخاب نشده است.",
  UPLOAD_FORMAT_NOT_ALLOWED: "قالب این فایل پشتیبانی نمی‌شود. قالب‌های مجاز: txt، md، pdf، docx، pptx، xlsx، csv و تصاویر.",
  UPLOAD_TOO_LARGE: "حجم فایل از ۲۵ مگابایت بیشتر است؛ این فایل پردازش نمی‌شود.",
  UPLOAD_TOO_MANY_FILES: "تعداد فایل‌های انتخابی زیاد است؛ در چند مرحله آپلود کنید.",
  STORAGE_QUOTA_EXCEEDED:
    "فضای ذخیره‌سازی سازمان شما پر شده است. برای افزایش فضا با پشتیبانی تماس بگیرید یا اسناد قدیمی را حذف کنید.",
  ASSET_FILE_MISSING: "فایل این سند روی سرور پیدا نشد.",
  EXTRACTION_FAILED: "متن این فایل قابل خواندن نبود؛ فایل ممکن است خراب باشد.",
  REVIEW_QUEUE: "این نوع فایل پردازش خودکار نمی‌شود و در صف بازبینی می‌ماند.",
  OCR_UNAVAILABLE: "موتور تشخیص متن تصویری روی سرور نصب نیست؛ سند در صف بازبینی ماند.",
  PROCESSING_JOB_NOT_FOUND: "کار پردازش موردنظر پیدا نشد.",
  JOB_NOT_RETRYABLE: "فقط کارهای ناموفق قابل تلاش مجدد هستند.",
  JOB_NOT_CANCELLABLE: "این کار در وضعیتی نیست که بتوان لغو کرد.",
  JOB_ATTEMPTS_EXHAUSTED: "این کار چند بار ناموفق بوده است؛ فایل را دوباره بارگذاری کنید.",
  EMPTY_QUERY: "متن پرسش خالی است.",

  // --- chat / execution / wallet --------------------------------------------
  CHAT_SESSION_NOT_FOUND: "گفتگوی موردنظر پیدا نشد.",
  EXECUTION_NOT_FOUND: "اجرای موردنظر پیدا نشد.",
  NOT_PENDING: "این اجرا در وضعیت مناسب شروع نیست.",
  NOT_RUNNING: "این اجرا در حال اجرا نیست.",
  ALREADY_TERMINAL: "این اجرا به پایان رسیده است.",
  ALREADY_CANCELLING: "لغو این اجرا از قبل در جریان است.",
  CITATIONS_NOT_ALLOWED: "برای این پاسخ امکان ثبت منبع وجود ندارد.",
  EXECUTION_TIMEOUT: "پردازش این پرسش بیش از حد طول کشید؛ دوباره تلاش کنید.",
  CREDIT_EXHAUSTED: "اعتبار حساب شما کافی نیست؛ ابتدا کیف پول را شارژ کنید.",
  WALLET_NOT_FOUND: "کیف پول این سازمان پیدا نشد.",
  REQUEST_DECIDED: "این درخواست شارژ قبلاً بررسی شده است.",
  SUBSCRIPTION_EXPIRED: "پلن سازمان منقضی شده است؛ برای ادامهٔ کار با پشتیبانی تماس بگیرید.",
  PROVIDER_NOT_CONFIGURED:
    "سرویس هوش مصنوعی هنوز تنظیم نشده است. کلید و نشانی سرویس را در پنل تنظیمات وارد کنید.",
  LLM_PROVIDER_UNAVAILABLE: "سرویس هوش مصنوعی در دسترس نیست؛ کمی بعد دوباره تلاش کنید.",
  LLM_PROVIDER_ERROR: "سرویس هوش مصنوعی پاسخ نداد؛ کمی بعد دوباره تلاش کنید.",
  // The provider reports an exhausted balance and a rate limit with the same
  // HTTP 429, so these stay separate: one means "top up", the other "slow down".
  LLM_PROVIDER_CREDIT:
    "اعتبار حساب سرویس هوش مصنوعی تمام شده است. اعتبار سرویس‌دهنده را شارژ کنید و دوباره تلاش کنید.",
  LLM_PROVIDER_RATE_LIMIT:
    "سرویس هوش مصنوعی درخواست‌ها را محدود کرده است؛ کمی بعد دوباره تلاش کنید.",
  LLM_PROVIDER_AUTH:
    "کلید سرویس هوش مصنوعی پذیرفته نشد. کلید را در پنل تنظیمات بررسی کنید.",
  LLM_PROVIDER_MODEL:
    "مدل انتخاب‌شده در سرویس هوش مصنوعی موجود نیست. نام مدل را در پنل بررسی کنید.",
  EMBEDDING_UNAVAILABLE: "سرویس جست‌وجوی معنایی در دسترس نیست.",

  // --- admin ----------------------------------------------------------------
  SETTING_NOT_FOUND: "این کلید تنظیمات وجود ندارد.",
  SETTING_SCHEMA_MISSING: "برای این کلید طرح اعتبارسنجی تعریف نشده است.",
  SETTING_VALIDATION_FAILED: "مقدار واردشده با قالب این تنظیمات سازگار نیست.",
  STREAM_NOT_FOUND: "جریان پاسخ پیدا نشد.",
  STREAM_LIMIT: "تعداد جریان‌های فعال زیاد است؛ کمی بعد دوباره تلاش کنید.",

  // --- generic --------------------------------------------------------------
  VALIDATION_ERROR: "اطلاعات واردشده کامل یا درست نیست؛ فیلدها را بررسی کنید.",
  VERSION_CONFLICT: "این مورد همزمان توسط کاربر دیگری تغییر کرده است؛ صفحه را به‌روز کنید.",
  INVALID_STATUS: "وضعیت فعلی اجازهٔ این کار را نمی‌دهد.",
  ALREADY_ARCHIVED: "این مورد از قبل بایگانی شده است.",
  NOT_ARCHIVED: "این مورد بایگانی نشده است.",
  CLIENT_BAD_RESPONSE: "پاسخ سرور قابل خواندن نبود؛ دوباره تلاش کنید.",
  CLIENT_TIMEOUT: "پاسخی از سرور دریافت نشد؛ دوباره تلاش کنید.",
  CLIENT_OFFLINE: "ارتباط با سرور برقرار نشد؛ اتصال شبکه را بررسی کنید.",
  INTERNAL_SERVER_ERROR: "خطای غیرمنتظره در سرور رخ داد؛ کمی بعد دوباره تلاش کنید.",
};

// Status-based fallback when the server sends a code we do not know yet.
const BY_STATUS: Record<number, string> = {
  400: "درخواست شما پذیرفته نشد؛ اطلاعات را بررسی کنید.",
  401: "برای این کار باید وارد حساب خود شوید.",
  402: "اعتبار حساب شما کافی نیست.",
  403: "اجازهٔ انجام این کار را ندارید.",
  404: "مورد درخواستی پیدا نشد.",
  409: "این کار با وضعیت فعلی سامانه سازگار نیست.",
  413: "حجم درخواست بیش از حد مجاز است.",
  429: "تعداد درخواست‌ها زیاد بود؛ چند لحظه بعد دوباره تلاش کنید.",
  500: "خطای غیرمنتظره در سرور رخ داد؛ کمی بعد دوباره تلاش کنید.",
  502: "سرور موقتاً پاسخ نمی‌دهد؛ کمی بعد دوباره تلاش کنید.",
  503: "سرویس موقتاً در دسترس نیست؛ کمی بعد دوباره تلاش کنید.",
  504: "سرور به‌موقع پاسخ نداد؛ دوباره تلاش کنید.",
};

/**
 * Persian text for one API failure.
 *
 * `serverMessage` is only used when the server itself already answered in
 * Persian (the few hand-written Persian API messages); anything else is
 * replaced by the mapped sentence so no English leaks into the UI.
 */
export function persianError(code: string, status = 0, serverMessage?: string | null): string {
  const mapped = MESSAGES[code];
  if (mapped) return mapped;
  if (serverMessage && /[\u0600-\u06FF]/.test(serverMessage)) return serverMessage;
  return BY_STATUS[status] ?? "انجام این کار ممکن نشد؛ دوباره تلاش کنید.";
}
