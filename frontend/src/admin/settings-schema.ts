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
  /** For numberMap: label of the "add row" action. */
  rowsLabel?: string
  /** Group heading — long settings pages get scannable sections. */
  group?: string
  tone?: StatusTone
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
        placeholder: "deepseek-v4.1-flash",
        hint: "مدلی که به پرسش کاربران پاسخ می‌دهد. خالی یعنی مقدار پیش‌فرض سرور. باید مدلی باشد که حساب شما برای آن اعتبار دارد.",
      },
      {
        name: "embedding_model",
        label: "مدل جست‌وجوی معنایی",
        kind: "text",
        ltr: true,
        group: "مدل‌ها",
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
        hint: "باید با ستون بردار در پایگاه داده هم‌خوان باشد؛ تغییر آن نیاز به بازسازی ایندکس دارد.",
      },
      {
        name: "rerank_provider",
        label: "روش بازچینی نتایج",
        kind: "select",
        group: "بازیابی",
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
        placeholder: "cohere-rerank-v4.0-fast",
      },
      {
        name: "credit_per_1000_tokens_out",
        label: "اعتبار به‌ازای هر ۱۰۰۰ توکن خروجی",
        kind: "number",
        min: 0,
        max: 10000,
        group: "قیمت‌گذاری",
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
        hint: "هر مدل در یک خط.",
        placeholder: "deepseek-v4.1-flash",
      },
      {
        name: "default",
        label: "مدل پیش‌فرض",
        kind: "text",
        ltr: true,
        required: true,
        placeholder: "deepseek-v4.1-flash",
        hint: "اگر کاربر مدلی انتخاب نکند، این مدل استفاده می‌شود.",
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
        hint: "پوشه اسناد هر این مدت یک‌بار بررسی و فایل‌های تازه پردازش می‌شوند.",
      },
      {
        name: "upload_max_file_mb",
        label: "سقف حجم هر فایل (مگابایت)",
        kind: "number",
        min: 1,
        max: 200,
        hint: "فایل بزرگ‌تر از این مقدار بارگذاری نمی‌شود.",
      },
      {
        name: "allowed_formats",
        label: "قالب‌های مجاز",
        kind: "list",
        ltr: true,
        hint: "پسوند فایل‌ها، هر کدام در یک خط (مثلاً pdf).",
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
        rowsLabel: "خط",
        hint: "نقش و محدودیت‌های دستیار را تعیین می‌کند.",
      },
      {
        name: "user_template",
        label: "قالب پرسش کاربر",
        kind: "multiline",
        required: true,
        hint: "باید شامل {question} و {context} باشد.",
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
