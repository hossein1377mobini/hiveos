// Persian numeral + phone formatting helpers shared across the wizard features.

export const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

// Renders Latin digits as Persian digits (۰-۹).
export function toFa(n: number | string): string {
  return String(n).replace(/\d/g, (d) => FA_DIGITS[+d]);
}

// Accepts Persian + Latin digits, strips everything else, forces the +98 prefix,
// caps at 10 digits. Returns the canonical "+98XXXXXXXXXX" form the API expects.
export function normalizePhone(raw: string): string {
  let s = raw.replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d)));
  s = s.replace(/^\+?98/, "").replace(/\D/g, "");
  s = s.slice(0, 10);
  return "+98" + s;
}

// Groups for readability (3-3-4): "+98 912 345 6789".
export function formatPhone(canonical: string): string {
  const d = canonical.slice(3);
  if (!d) return "+98";
  if (d.length <= 3) return "+98 " + d;
  if (d.length <= 6) return "+98 " + d.slice(0, 3) + " " + d.slice(3);
  return "+98 " + d.slice(0, 3) + " " + d.slice(3, 6) + " " + d.slice(6);
}
