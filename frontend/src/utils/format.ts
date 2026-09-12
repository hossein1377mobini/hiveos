// Display formatting — design-system §1.1 (ارقام فارسی در نمایش) and §3.2
// (نرمال‌سازی ارقام برای جستجو). Technical fields keep Latin digits.

const FA_DIGITS = /[\u06F0-\u06F9]/g;
const AR_DIGITS = /[\u0660-\u0669]/g;

/** Latin digits for data/compare contexts (search normalization source: mockup norm()). */
export function normDigits(value: string): string {
  return value
    .replace(FA_DIGITS, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(AR_DIGITS, (d) => String(d.charCodeAt(0) - 0x0660));
}

/** Full search normalization: digit conversion + trim + ZWNJ handling. */
export function norm(value: string): string {
  return normDigits(value).trim().toLowerCase();
}

/** Format a number with Persian digits + thousand separators (fa-IR). */
export function faNum(value: number | string): string {
  const n = typeof value === "number" ? value : Number(normDigits(value).replace(/[^0-9.-]/g, ""));
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 }).format(n);
}

/** Jalali date + time, Persian digits (design-system §3.2). */
export function faDateTime(value: string | number | Date): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

/** Jalali date only, Persian digits. */
export function faDate(value: string | number | Date): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

/** Time only (HH:MM), Persian digits. */
export function faTime(value: string | number | Date): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(d);
}

/** Bytes → human size, Latin digits (technical field). */
export function humanSize(bytes: number): string {
  if (!Number.isFinite(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return (u === 0 ? String(v) : v.toFixed(1)) + " " + units[u];
}
