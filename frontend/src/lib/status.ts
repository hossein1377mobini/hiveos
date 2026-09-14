/**
 * Single source of truth for domain status presentation. [B7]
 *
 * v0.1 coloured status in two unrelated places: ui/status-badge.tsx for the
 * knowledge table and a hand-written STATUS_FA map inside the admin panel.
 * Both are replaced by this map, so a status can never mean two colours.
 */

export type StatusTone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "error"
  | "teal"
  | "amber"
  | "violet";

export interface StatusPresentation {
  /** Persian label shown to the user. */
  label: string;
  tone: StatusTone;
  /** One-line explanation for tooltips and audit rows. */
  hint?: string;
}

const NEUTRAL: StatusPresentation = { label: "نامشخص", tone: "neutral" };

/** Organization lifecycle (organizations.status). */
const ORGANIZATION: Record<string, StatusPresentation> = {
  pending: { label: "در انتظار تأیید", tone: "warning", hint: "ثبت‌نام کامل نشده است." },
  active: { label: "فعال", tone: "success", hint: "سازمان فعال و بدون محدودیت." },
  suspended: { label: "معلق", tone: "neutral", hint: "دسترسی کاربران قطع شده است." },
  expired: { label: "منقضی", tone: "error", hint: "اشتراک به پایان رسیده است." },
};

/**
 * Knowledge asset pipeline (assets.status).
 *
 * The wording follows the PO's decision recorded in the v0.1 mockup index
 * ("استاندارد یکپارچه: در صف · در حال پردازش · در حال تلاش مجدد · تکمیل شد ·
 * ناموفق · متوقف"), not the API's own enum names. The API says READY/INDEXED/
 * SUCCEEDED for what the product calls one thing, so all three aliases resolve
 * here instead of each screen picking one.
 */
const ASSET: Record<string, StatusPresentation> = {
  pending: { label: "در صف", tone: "neutral" },
  queued: { label: "در صف", tone: "neutral" },
  processing: { label: "در حال پردازش", tone: "info" },
  retrying: { label: "در حال تلاش مجدد", tone: "warning" },
  indexed: { label: "تکمیل شد", tone: "success" },
  ready: { label: "تکمیل شد", tone: "success" },
  succeeded: { label: "تکمیل شد", tone: "success" },
  needs_review: { label: "نیازمند بازبینی", tone: "warning", hint: "متن سند کامل استخراج نشد." },
  stopped: { label: "متوقف", tone: "neutral" },
  deleted: { label: "حذف‌شده", tone: "neutral" },
  failed: { label: "ناموفق", tone: "error" },
  parse_failed: { label: "خطای پردازش", tone: "error" },
  cancelled: { label: "لغو‌شده", tone: "neutral" },
  skipped: { label: "نادیده‌گرفته‌شده", tone: "neutral" },
  duplicate: { label: "تکراری", tone: "neutral" },
};

/** Processing jobs / queue (processing_jobs.status). */
const JOB: Record<string, StatusPresentation> = {
  queued: { label: "در صف", tone: "neutral" },
  running: { label: "در حال اجرا", tone: "info" },
  succeeded: { label: "انجام‌شده", tone: "success" },
  failed: { label: "ناموفق", tone: "error" },
  cancelled: { label: "لغو‌شده", tone: "neutral" },
  retrying: { label: "تلاش مجدد", tone: "warning" },
  retry: { label: "تلاش مجدد", tone: "warning" },
};

/** Subscription plan (organizations.plan). */
const PLAN: Record<string, StatusPresentation> = {
  trial: { label: "آزمایشی", tone: "amber" },
  monthly: { label: "ماهانه", tone: "info" },
  quarterly: { label: "سه‌ماهه", tone: "info" },
  semiannual: { label: "شش‌ماهه", tone: "teal" },
  annual: { label: "یک‌ساله", tone: "violet" },
  none: { label: "بدون اشتراک", tone: "neutral" },
  suspended: { label: "معلق", tone: "neutral" },
};

/** Charge request decision state. */
// The charge-request API answers uppercase PENDING/APPROVED/REJECTED while every
// other endpoint in the product answers lowercase; statusOf lowercases the key,
// so both spellings resolve to the same presentation.
const CHARGE_REQUEST: Record<string, StatusPresentation> = {
  pending: { label: "در انتظار تأیید", tone: "warning" },
  approved: { label: "تأییدشده", tone: "success" },
  rejected: { label: "رد‌شده", tone: "error" },
  granted: { label: "تأییدشده", tone: "success" },
  denied: { label: "رد‌شده", tone: "error" },
};

/** Health probes (system status, backup, provider test). */
const HEALTH: Record<string, StatusPresentation> = {
  // The backend's system-status contract uses green/degraded/red; the provider
  // and backup probes use ok/degraded/failed. Both live here so no view has to
  // know which probe it is looking at.
  green: { label: "سالم", tone: "success" },
  red: { label: "اختلال", tone: "error" },
  ok: { label: "سالم", tone: "success" },
  healthy: { label: "سالم", tone: "success" },
  degraded: { label: "نیازمند بررسی", tone: "warning" },
  warn: { label: "هشدار", tone: "warning" },
  slow: { label: "کند", tone: "warning" },
  stale: { label: "قدیمی‌تر از موعد", tone: "warning", hint: "آخرین اجرا از بازهٔ مورد انتظار گذشته است." },
  down: { label: "قطع", tone: "error" },
  error: { label: "خطا", tone: "error" },
  unavailable: { label: "در دسترس نیست", tone: "error" },
  unknown: { label: "نامشخص", tone: "neutral" },
};

/** Knowledge source watch state (knowledge_sources.status). */
const SOURCE: Record<string, StatusPresentation> = {
  active: { label: "فعال", tone: "success" },
  disabled: { label: "غیرفعال", tone: "neutral" },
};

/** Event-log severity used by the admin activity view. */
const SEVERITY: Record<string, StatusPresentation> = {
  info: { label: "اطلاع", tone: "info" },
  activity: { label: "فعالیت", tone: "info" },
  warning: { label: "هشدار", tone: "warning" },
  error: { label: "خطا", tone: "error" },
  critical: { label: "بحرانی", tone: "error" },
};

const REGISTRIES: Record<string, Record<string, StatusPresentation>> = {
  organization: ORGANIZATION,
  asset: ASSET,
  job: JOB,
  plan: PLAN,
  charge: CHARGE_REQUEST,
  source: SOURCE,
  health: HEALTH,
  severity: SEVERITY,
};

export type StatusDomain = keyof typeof REGISTRIES;

/**
 * Resolve a raw status value into its label and tone.
 * Unknown values degrade to the raw string in a neutral tone rather than
 * vanishing, so a new backend status is visible (if unstyled) on day one.
 */
export function statusOf(domain: StatusDomain, value: string | null | undefined): StatusPresentation {
  if (!value) return NEUTRAL;
  const key = value.toLowerCase();
  return REGISTRIES[domain]?.[key] ?? { label: value, tone: "neutral" };
}
