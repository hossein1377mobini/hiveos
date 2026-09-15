import type { StatusTone } from "../lib/status"

/**
 * Settings field descriptors.
 *
 * v0.1 rendered all five admin settings as raw JSON textareas. Configuring the
 * product — the PO's own stated job — meant hand-writing JSON with no validation,
 * no enum hints and no way to see what a valid value looked like; a typo was
 * discovered by the backend rejecting the save, or worse, by a chat request
 * failing an hour later. [D8/D13/A3]
 *
 * Each descriptor mirrors the Pydantic model the backend validates against
 * (_SETTING_SCHEMAS in backend/admin.py), so a value the form accepts is a value
 * the server accepts. Constraints (min/max/enum) are enforced here rather than
 * round-tripped through a 422.
 */

export type FieldKind = "text" | "password" | "number" | "select" | "list" | "multiline" | "numberMap"

export interface SettingField {
  name: string
  label: string
  kind: FieldKind
  /** Plain-language help, always Persian, never a code identifier. */
  hint?: string
  /** Shown inside the empty control. */
  placeholder?: string
  required?: boolean
  /** Render LTR — paths, keys, model names and URLs are Latin values. */
  ltr?: boolean
  min?: number
  max?: number
  /** For select. The first entry is the backend default when the value is unset. */
  options?: Array<{ value: string; label: string }>
  /** For numberMap: the noun used by the "add row" action. */
  rowsLabel?: string
  /** Group heading — long settings pages get scannable sections. */
  group?: string
  tone?: StatusTone
  /**
   * For multiline: the API field under `default` that holds the shipped value.
   * When set, the control offers "restore the suggested text". The default is
   * fetched from the server rather than copied here, so it cannot drift from
   * the prompt the runtime actually falls back to.
   */
  defaultFrom?: string
  /**
   * The value the runtime uses when this field is absent from the stored
   * object, rendered as a "مقدار پیشفرض" note.
   *
   * The PO opened the pipeline panel, saw an empty "سقف حجم هر فایل", and read
   * it as "no limit" — while the server was enforcing 25 MB on every upload.
   * An empty control must never imply "nothing is in force". Every value here
   * is copied from the Pydantic model the backend validates against
   * (_SETTING_SCHEMAS in backend/admin.py) or, for provider values, from
   * backend/config.py; the report accompanying this change asks the backend to
   * start sending a `default` object per key, exactly as it already does for
   * prompt_template, so this mirror can be deleted rather than maintained.
   */
  effectiveDefault?: string | number
  /** Row count for a multiline control. Larger for the prompt editor. */
  rows?: number
}

export interface SettingDefinition {
  key: string
  title: string
  /** What this setting changes, in the operator's terms. */
  description: string
  fields: SettingField[]
}

export const SETTING_DEFINITIONS: SettingDefinition[] = [
  {
    key: "providers_pricing",
    title: "درگاه مدل و قیمت",
    description:
      "اتصال به درگاه هوش مصنوعی و نرخ تبدیل مصرف به اعتبار. کلید درگاه فقط اینجا نگه‌داری می‌شود و هرگز به کاربران نمایش داده نمی‌شود.",
    fields: [
      {
        name: "provider",
        label: "درگاه فعال",
        kind: "select",
        required: true,
        group: "اتصال",
        effectiveDefault: "mock",
        options: [
          { value: "mock", label: "آزمایشی (بدون اتصال بیرونی)" },
          { value: "online-mock", label: "آزمایشی آنلاین" },
          { value: "openai-compatible", label: "سازگار با OpenAI" },
        ],
      },
      {
        name: "base_url",
        label: "نشانی درگاه",
        kind: "text",
        ltr: true,
        group: "اتصال",
        placeholder: "https://api.example.com/v1",
        hint: "فقط برای درگاه سازگار با OpenAI لازم است.",
      },
      {
        name: "api_key",
        label: "کلید درگاه",
        kind: "password",
        ltr: true,
        group: "اتصال",
        hint: "در فهرست پایش، فقط بخش پایانی کلید نمایش داده می‌شود.",
      },
      {
        name: "answer_model",
        label: "مدل پاسخ‌دهی",
        kind: "text",
        ltr: true,
        group: "مدل‌ها",
        effectiveDefault: "gpt-5-mini",
        placeholder: "deepseek-v4.1-flash",
        hint: "مدلی که به پرسش کاربران پاسخ می‌دهد. خالی یعنی مقدار پیش‌فرض سرور. باید مدلی باشد که حساب شما برای آن اعتبار دارد.",
      },
      {
        name: "embedding_model",
        label: "مدل جست‌وجوی معنایی",
        kind: "text",
        ltr: true,
        group: "مدل‌ها",
        effectiveDefault: "text-embedding-3-large",
        placeholder: "text-embedding-3-large",
        hint: "برای تبدیل اسناد به بردار جست‌وجو استفاده می‌شود.",
      },
      {
        name: "embedding_dimensions",
        label: "ابعاد بردار",
        kind: "number",
        min: 256,
        max: 3072,
        group: "مدل‌ها",
        effectiveDefault: 1024,
        hint: "باید با ستون بردار در پایگاه داده هم‌خوان باشد؛ تغییر آن نیاز به بازسازی ایندکس دارد.",
      },
      {
        name: "rerank_provider",
        label: "روش بازچینی نتایج",
        kind: "select",
        group: "بازیابی",
        effectiveDefault: "onnx",
        options: [
          { value: "onnx", label: "روی همین سرور (پیش‌فرض)" },
          { value: "remote", label: "سرویس بیرونی" },
          { value: "off", label: "بدون بازچینی" },
        ],
      },
      {
        name: "rerank_model",
        label: "مدل بازچینی",
        kind: "text",
        ltr: true,
        group: "بازیابی",
        effectiveDefault: "cohere-rerank-v4.0-fast",
        placeholder: "cohere-rerank-v4.0-fast",
      },
      {
        name: "credit_per_1000_tokens_out",
        label: "اعتبار به‌ازای هر ۱۰۰۰ توکن خروجی",
        kind: "number",
        min: 0,
        max: 10000,
        group: "قیمت‌گذاری",
        effectiveDefault: 1,
        hint: "مبنای کسر اعتبار از کیف پول سازمان‌ها. صفر یعنی مصرف رایگان.",
      },
    ],
  },
  {
    key: "models_allowlist",
    title: "لیست مدل‌های مجاز",
    description:
      "کاربران فقط می‌توانند از میان این مدل‌ها انتخاب کنند. اگر مدلی اینجا نباشد، درخواست پاسخ نمی‌گیرد.",
    fields: [
      {
        name: "models",
        label: "مدل‌های مجاز",
        kind: "list",
        ltr: true,
        hint:
          "هر مدل در یک خط. این فهرست برخلاف «سقف حجم فایل» پیش‌فرضی ندارد: " +
          "خالی بودنش یعنی هیچ مدلی محدود نشده و هر مدلی که درگاه بشناسد پذیرفته می‌شود؛ " +
          "پر بودنش یعنی کاربر فقط می‌تواند از میان همین‌ها انتخاب کند.",
        placeholder: "deepseek-v4.1-flash",
      },
      {
        name: "default",
        label: "مدل پیش‌فرض",
        kind: "text",
        ltr: true,
        required: true,
        placeholder: "deepseek-v4.1-flash",
        hint:
          "اگر کاربر مدلی انتخاب نکند، این مدل استفاده می‌شود. " +
          "وقتی «مدل‌های مجاز» خالی باشد این مقدار نادیده گرفته می‌شود.",
      },
    ],
  },
  {
    key: "pipeline",
    title: "پایپ‌لاین اسناد",
    description: "زمان‌بندی پویش پوشه اسناد و محدودیت بارگذاری فایل.",
    fields: [
      {
        name: "scan_interval_minutes",
        label: "فاصلهٔ پویش پوشه (دقیقه)",
        kind: "number",
        min: 1,
        max: 10080,
        effectiveDefault: 30,
        hint:
          "پوشهٔ اسناد با این فاصله بررسی و فایل‌های تازه پردازش می‌شوند. " +
          "هر منبع دانش می‌تواند فاصلهٔ خودش را داشته باشد؛ این عدد پیش‌فرضِ منابعی است که فاصلهٔ اختصاصی ندارند.",
      },
      {
        name: "upload_max_file_mb",
        label: "سقف حجم هر فایل (مگابایت)",
        kind: "number",
        min: 1,
        max: 200,
        effectiveDefault: 25,
        hint:
          "فایل بزرگ‌تر از این مقدار نه بارگذاری می‌شود و نه از پوشهٔ اسناد خوانده می‌شود؛ " +
          "سرور هنگام دریافت و هنگام پویش پوشه همین سقف را اعمال می‌کند. " +
          "خالی گذاشتن یعنی محدودیتی اعمال نشده و همان مقدار پیش‌فرض سرور (۲۵ مگابایت) برقرار است.",
      },
      {
        name: "allowed_formats",
        label: "قالب‌های مجاز",
        kind: "list",
        ltr: true,
        hint:
          "پسوند فایل‌ها، هر کدام در یک خط (مثلاً pdf). " +
          "خالی گذاشتن یعنی سرور خودش قالب‌ها را محدود نمی‌کند و همهٔ قالب‌های پشتیبانی‌شده پذیرفته می‌شوند — این فیلد برخلاف «سقف حجم فایل» سقف پیش‌فرضی ندارد.",
        placeholder: "pdf",
      },
    ],
  },
  {
    key: "prompt_template",
    title: "قالب پرامپت",
    description:
      "نحوهٔ ساخت پرسش نهایی از سؤال کاربر و متن بازیابی‌شده. جای‌نگهدارهای {question} و {context} باید حفظ شوند.",
    fields: [
      {
        name: "system",
        label: "دستور سیستمی",
        kind: "multiline",
        rows: 22,
        defaultFrom: "system",
        hint:
          "نقش، قواعد پاسخ‌گویی، لحن و قالب‌بندی دستیار. اگر خالی بماند متن پیشنهادی خود محصول استفاده می‌شود. " +
          "جای‌نگهدار {business_description} با توصیف کسب‌وکار سازمان پر می‌شود؛ اگر حذفش کنید دستیار نمی‌داند در چه کسب‌وکاری پاسخ می‌دهد.",
      },
      {
        name: "user_template",
        label: "قالب پرسش کاربر",
        kind: "multiline",
        required: true,
        rows: 6,
        defaultFrom: "user_template",
        hint:
          "چیدمان پرسش کاربر و متن بازیابی‌شده. باید شامل {question} و {context} باشد.",
      },
    ],
  },
  // Placed directly after prompt_template on purpose: the persona and the
  // system prompt are merged into the same instruction before the model sees
  // it, so an operator editing one must be able to read the other. The page
  // itself no longer decides its own order from this array — AiView's
  // AI_SECTIONS owns the reading order — but the pairing is why these two stay
  // neighbours there too.
  {
    key: "agent",
    title: "تنظیمات ایجنت سازمان",
    description:
      "رفتار دستیار برای همهٔ کاربران سازمان، در یک جا و همراه با تنظیمات پاسخ‌دهی هوش مصنوعی. " +
      "شخصیت و ابزارهای دستیار تصمیم سازمان است، نه سلیقهٔ هر کاربر: دستیار به نمایندگی از سازمان پاسخ می‌دهد و پاسخ به نام سازمان ثبت می‌شود. " +
      "نام نمایشی هر کاربر را خودش جداگانه تغییر می‌دهد.",
    fields: [
      {
        name: "display_name",
        label: "نام پیش‌فرض دستیار",
        kind: "text",
        required: true,
        group: "شخصیت و ابزارها",
        effectiveDefault: "دستیار سازمان",
        placeholder: "دستیار سازمان",
        hint: "نامی که دستیار تازه با آن ساخته می‌شود. هر کاربر بعداً می‌تواند نام نمایشی خودش را جدا تغییر دهد.",
      },
      {
        name: "persona",
        label: "شخصیت و لحن",
        kind: "multiline",
        rows: 8,
        group: "شخصیت و ابزارها",
        placeholder: "مثلاً همیشه کوتاه و رسمی پاسخ بده…",
        hint:
          "این متن به دستور سیستمی سازمان اضافه می‌شود، نه اینکه جای آن را بگیرد. " +
          "یعنی لحن و سبک را تعیین می‌کند ولی هرگز نمی‌تواند قواعد استناد، ارجاع و پاسخ‌گویی مستند را کنار بزند؛ " +
          "شخصیت روی زمینِ سازمان سوار می‌شود، روی آن سوار نمی‌شود. خالی بگذارید تا فقط دستور سیستمی اعمال شود.",
      },
      {
        name: "allowed_tools",
        label: "ابزارهای مجاز",
        kind: "list",
        ltr: true,
        group: "شخصیت و ابزارها",
        placeholder: "build_chart",
        hint:
          "نام دقیق ابزارها، هر کدام در یک خط — مثلاً build_chart (ساخت نمودار) و build_report (ساخت گزارش). " +
          "خالی گذاشتن یعنی همهٔ ابزارهای موجود فعال باشند. ابزاری که اینجا نباشد، دستیار اجازهٔ صدا زدنش را ندارد. " +
          "این فهرست باز است و برای همهٔ کاربران سازمان اعمال می‌شود؛ هر نامی که بنویسید همان ذخیره می‌شود.",
      },
      {
        name: "memory_enabled",
        label: "استفاده از حافظه",
        kind: "select",
        required: true,
        group: "حافظه",
        effectiveDefault: "true",
        options: [
          { value: "true", label: "فعال — دستیار از خاطره‌ها استفاده می‌کند" },
          { value: "false", label: "غیرفعال — دستیار از خاطره‌ها استفاده نمی‌کند" },
        ],
        hint:
          "خاموش کردن آن استفاده از حافظه را متوقف می‌کند، ولی خاطره‌های ذخیره‌شده را پاک نمی‌کند؛ " +
          "با روشن کردن دوباره، همان خاطره‌ها برمی‌گردند.",
      },
      {
        name: "recall_limit",
        label: "تعداد خاطره‌های بازیابی‌شده",
        kind: "number",
        min: 1,
        max: 50,
        group: "حافظه",
        effectiveDefault: 6,
        hint:
          "بیشترین تعداد خاطره‌ای که در هر پرسش پیش روی مدل گذاشته می‌شود. " +
          "عدد بزرگ‌تر یعنی زمینهٔ بیشتر دربارهٔ کاربر و در عوض پرسش سنگین‌تر؛ عدد کوچک‌تر یعنی پاسخ سبک‌تر ولی کم‌حافظه‌تر. خالی یعنی مقدار پیش‌فرض سرور (۶).",
      },
      {
        name: "trust_gain",
        label: "وزن خاطره‌های اثبات‌شده",
        kind: "number",
        min: 0,
        max: 2,
        group: "حافظه",
        effectiveDefault: 0.25,
        hint:
          "میزان برتری خاطره‌ای که در پاسخ‌های پیشین مفید بوده، نسبت به خاطره‌ای که فقط شبیه پرسش فعلی است. " +
          "صفر یعنی این برتری به‌کل بی‌اثر است و انتخاب خاطره‌ها فقط بر پایهٔ شباهت انجام می‌شود؛ عدد بالاتر یعنی تجربهٔ اثبات‌شده سریع‌تر بالاتر می‌نشیند. خالی یعنی مقدار پیش‌فرض سرور (۰٫۲۵).",
      },
    ],
  },
  // "subscription" deliberately has no entry here.
  //
  // The definition used to exist and rendered a tab whose GET always answered
  // 404 SETTING_NOT_FOUND: admin.py's SETTINGS_KEYS omits it, and no code reads
  // trial_days or plans, so the form could never load and saving would have had
  // no effect on any organization. A settings tab that cannot work is worse
  // than an absent one, so it is gone until the subscription lifecycle actually
  // reads these values. [D8/D13]
]

export function settingByKey(key: string): SettingDefinition | undefined {
  return SETTING_DEFINITIONS.find((setting) => setting.key === key)
}
