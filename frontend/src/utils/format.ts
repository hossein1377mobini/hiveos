/**
 * Legacy formatting entry point.
 *
 * v0.5 moved every helper into lib/dates.ts so the app and the admin panel stop
 * carrying private copies of the same formatter. This module stays as a thin
 * re-export because the pages import from here; new code imports lib/dates.
 */
export {
  faNum,
  faDigit,
  faDate,
  faDateShort,
  faTime,
  faDateTime,
  faRelative,
  humanSize,
  bytesToMb,
  norm,
} from "../lib/dates";

/** Latin digits for data/compare contexts. */
export function normDigits(value: string): string {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/[\u06F0-\u06F9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660));
}
