/**
 * Persian-first date and number formatting. [D14-adjacent]
 *
 * v0.1 had utils/format.ts for the app plus two private copies of the same
 * helpers inside the admin panel (AdminApp.faNum and MonitoringTab's own
 * formatter), which had already drifted apart. Everything routes through here.
 */

const FA_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

const numberFormatter = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 });

/**
 * Persian digits with thousands separators.
 *
 * Pass `digits` to pin the decimal places — gauges and rates need a stable
 * width ("۲۳٫۵٪" must not become "۲۳٫۵۰٪" on one poll and "۲۳٪" on the next), so
 * the formatters are cached per digit count rather than rebuilt per render.
 */
const fixedFormatters = new Map<number, Intl.NumberFormat>();

export function faNum(value: number | string | null | undefined, digits?: number): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  if (digits === undefined) return numberFormatter.format(n);
  let formatter = fixedFormatters.get(digits);
  if (!formatter) {
    formatter = new Intl.NumberFormat("fa-IR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    fixedFormatters.set(digits, formatter);
  }
  return formatter.format(n);
}

/**
 * A calendar year in Persian digits, with no thousands separator.
 *
 * `faNum(1405)` renders «۱٬۴۰۵» — correct for a quantity, wrong for a year, and
 * the mistake is invisible in Latin-digit review. Years go through this.
 */
export function faYear(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return String(value).replace(/[0-9]/g, (digit) => FA_DIGITS[Number(digit)]);
}

/** Convert Latin digits inside an arbitrary string to Persian digits. */
export function faDigit(input: string | number): string {
  return String(input).replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)]);
}

const dateFormatter = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

const shortDateFormatter = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const timeFormatter = new Intl.DateTimeFormat("fa-IR", {
  hour: "2-digit",
  minute: "2-digit",
});

const dateTimeFormatter = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function parse(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** «۱۴ شهریور ۱۴۰۵» */
export function faDate(value: string | number | Date | null | undefined): string {
  const d = parse(value);
  return d ? dateFormatter.format(d) : "—";
}

/** «۱۴۰۵/۰۶/۱۴» — table cells. */
export function faDateShort(value: string | number | Date | null | undefined): string {
  const d = parse(value);
  return d ? shortDateFormatter.format(d) : "—";
}

/** «۱۴:۳۲» */
export function faTime(value: string | number | Date | null | undefined): string {
  const d = parse(value);
  return d ? timeFormatter.format(d) : "—";
}

/** «۱۴۰۵/۰۶/۱۴ ۱۴:۳۲» — audit and log rows. */
export function faDateTime(value: string | number | Date | null | undefined): string {
  const d = parse(value);
  return d ? dateTimeFormatter.format(d) : "—";
}

/** «۲ دقیقه پیش» / «۳ روز پیش» — relative age for activity feeds. */
export function faRelative(value: string | number | Date | null | undefined, now = new Date()): string {
  const d = parse(value);
  if (!d) return "—";
  const seconds = Math.round((now.getTime() - d.getTime()) / 1000);
  if (seconds < 45) return "همین حالا";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return faNum(minutes) + " دقیقه پیش";
  const hours = Math.round(minutes / 60);
  if (hours < 24) return faNum(hours) + " ساعت پیش";
  const days = Math.round(hours / 24);
  if (days < 30) return faNum(days) + " روز پیش";
  return faDateShort(d);
}

const sizeUnits = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"];

/**
 * File size. Digits stay Latin per design-system §۱.۱: sizes are technical
 * values compared against a quota that is configured in Latin digits.
 */
export function humanSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return bytes + " B";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < sizeUnits.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return value.toFixed(value >= 10 ? 0 : 1) + " " + sizeUnits[unit];
}

/** Bytes → megabytes, for the storage-quota control. */
export function bytesToMb(bytes: number): number {
  return Math.round(bytes / (1024 * 1024));
}

/**
 * Normalize Persian/Arabic characters before comparing or filtering.
 * ZWNJ is preserved: stripping it changes word boundaries in Persian.
 */
export function norm(input: string): string {
  return input
    .replace(/[\u064A\u0649]/g, "\u06CC")
    .replace(/[\u0643]/g, "\u06A9")
    .replace(/[\u06F0-\u06F9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .toLowerCase()
    .trim();
}
/* ------------------------------------------------------------------ *
 * Jalali calendar arithmetic
 *
 * The product needs a Persian date picker (design-system §۳.۱ records it as a
 * requirement and v0.1 never shipped one, so the events view could only filter
 * by level — D15). \`Intl\` can *format* a Jalali date but cannot do month
 * arithmetic on one: asking "what is the first day of the previous Jalali
 * month?" is not expressible through the formatter.
 *
 * The conversion below is the standard Khayyam/Birashk-free algorithm used by
 * jalaali-js (the same one behind most Persian date pickers). It is inlined
 * rather than pulling in a dependency because the frontend has to run
 * air-gapped and this is ~40 lines of pure arithmetic.
 * ------------------------------------------------------------------ */

interface JalaliParts {
  year: number;
  month: number; // 1-12
  day: number; // 1-31
}

const div = (a: number, b: number) => Math.floor(a / b);

/** Gregorian Date → Jalali parts. */
function toJalali(date: Date): JalaliParts {
  const gy = date.getFullYear();
  const gm = date.getMonth() + 1;
  const gd = date.getDate();
  const g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];

  let jy = gy <= 1600 ? 0 : 979;
  const gy2 = gy <= 1600 ? gy - 621 : gy - 1600;
  const gm2 = gm > 2 ? 1 : 0;
  let days =
    365 * gy2 +
    div(gy2 + 3 + gm2, 4) -
    div(gy2 + 99 + gm2, 100) +
    div(gy2 + 399 + gm2, 400) -
    80 +
    gd +
    g_d_m[gm - 1];
  jy += 33 * div(days, 12053);
  days %= 12053;
  jy += 4 * div(days, 1461);
  days %= 1461;
  if (days > 365) {
    jy += div(days - 1, 365);
    days = (days - 1) % 365;
  }
  const jm = days < 186 ? 1 + div(days, 31) : 7 + div(days - 186, 30);
  const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
  return { year: jy, month: jm, day: jd };
}

/** Jalali parts → Gregorian Date (local midnight). */
function toGregorian({ year: jy, month: jm, day: jd }: JalaliParts): Date {
  let gy = jy <= 979 ? 621 : 1600;
  const jy2 = jy <= 979 ? jy : jy - 979;
  let days =
    365 * jy2 +
    div(jy2, 33) * 8 +
    div((jy2 % 33) + 3, 4) +
    78 +
    jd +
    (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
  gy += 400 * div(days, 146097);
  days %= 146097;
  if (days > 36524) {
    gy += 100 * div(--days, 36524);
    days %= 36524;
    if (days >= 365) days++;
  }
  gy += 4 * div(days, 1461);
  days %= 1461;
  if (days > 365) {
    gy += div(days - 1, 365);
    days = (days - 1) % 365;
  }
  let gd = days + 1;
  const leap = (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0;
  const sal_a = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let gm = 0;
  for (gm = 0; gm < 13 && gd > sal_a[gm]; gm++) gd -= sal_a[gm];
  return new Date(gy, gm - 1, gd);
}

/** Number of days in a Jalali month (months 1-6: 31, 7-11: 30, 12: 29 or 30). */
function jalaliMonthLength(year: number, month: number): number {
  if (month <= 6) return 31;
  if (month <= 11) return 30;
  // Esfand has 30 days in a leap year. Comparing the day count of the year's
  // start to the next year's start is the cheapest reliable test.
  const start = toGregorian({ year, month: 1, day: 1 }).getTime();
  const next = toGregorian({ year: year + 1, month: 1, day: 1 }).getTime();
  return Math.round((next - start) / 86_400_000) > 365 ? 30 : 29;
}

export interface JalaliMonth {
  year: number;
  month: number;
  /** Persian month name, e.g. «شهریور». */
  label: string;
  /** Days in this month, each with its Jalali day number and Gregorian date. */
  days: Array<{ day: number; date: Date; iso: string; isToday: boolean }>;
  /** Weekday index (0=Saturday … 6=Friday) of the first day, for grid offset. */
  leadingBlanks: number;
}

const MONTH_NAMES = [
  "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
];

/** Every day of the Jalali month containing \`anchor\`, ready to render as a grid. */
export function jalaliMonth(anchor: Date, today = new Date()): JalaliMonth {
  const { year, month } = toJalali(anchor);
  const length = jalaliMonthLength(year, month);
  const first = toGregorian({ year, month, day: 1 });

  const todayDate = new Date(today);
  todayDate.setHours(0, 0, 0, 0);

  const days: JalaliMonth["days"] = [];
  for (let day = 1; day <= length; day += 1) {
    const date = toGregorian({ year, month, day });
    date.setHours(0, 0, 0, 0);
    days.push({
      day,
      date,
      iso: date.toISOString(),
      isToday: date.getTime() === todayDate.getTime(),
    });
  }

  // JS getDay(): 0=Sunday. The Persian week starts on Saturday, so Saturday (6)
  // maps to column 0.
  const leadingBlanks = (first.getDay() + 1) % 7;

  return { year, month, label: MONTH_NAMES[month - 1], days, leadingBlanks };
}

/** Shift a Gregorian anchor by \`delta\` Jalali months, clamped to day 1. */
export function shiftJalaliMonth(anchor: Date, delta: number): Date {
  const { year, month } = toJalali(anchor);
  // Count months from year 0 so December→January wraps without a special case.
  const total = year * 12 + (month - 1) + delta;
  return toGregorian({ year: Math.floor(total / 12), month: (total % 12) + 1, day: 1 });
}

/** «شهریور ۱۴۰۵» for a month header. */
export function faMonthTitle(anchor: Date): string {
  const { year, month } = toJalali(anchor);
  return MONTH_NAMES[month - 1] + " " + faYear(year);
}

/** Persian weekday initials, Saturday first. */
export const FA_WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
