import { describe, expect, it } from "vitest";
import {
  FA_WEEKDAYS,
  faMonthTitle,
  jalaliMonth,
  shiftJalaliMonth,
} from "./dates";

/**
 * Jalali arithmetic is the one piece of the date layer that can be wrong without
 * looking wrong: a picker one day off still renders a plausible calendar. These
 * tests check the conversion against the platform's own Intl Persian calendar,
 * which is an independent implementation, and cover the known-hard cases
 * (Esfand in a leap year, the year boundary, the 31→30 month shift).
 */

/** The platform's Jalali rendering of a date, as year/month/day numbers. */
function viaIntl(date: Date): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat("en-u-ca-persian-nu-latn", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    timeZone: "UTC",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? "0");
  return { year: get("year"), month: get("month"), day: get("day") };
}

describe("jalaliMonth", () => {
  it("agrees with Intl on every day of a sampled year", () => {
    // Walk a Gregorian year day by day and compare the Jalali day number the
    // grid would show with what Intl says — a single off-by-one anywhere fails.
    const start = new Date(Date.UTC(2025, 0, 1));
    for (let i = 0; i < 365; i += 1) {
      const date = new Date(start.getTime() + i * 86_400_000);
      const local = new Date(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
      const month = jalaliMonth(local, local);
      const entry = month.days.find((d) => d.date.getTime() === local.getTime());
      expect(entry, local.toISOString()).toBeDefined();
      const expected = viaIntl(new Date(Date.UTC(local.getFullYear(), local.getMonth(), local.getDate())));
      expect({ y: month.year, m: month.month, d: entry!.day }, local.toISOString()).toEqual({
        y: expected.year,
        m: expected.month,
        d: expected.day,
      });
    }
  });

  it("gives Esfand 29 days in a common year and 30 in a leap year", () => {
    // Leap years are not on a Gregorian schedule, so which Esfand is the long
    // one is found rather than assumed. 1403 (starts 21 Mar 2024) is leap.
    const esfand1403 = jalaliMonth(new Date(2025, 1, 25), new Date(2025, 1, 25));
    expect(esfand1403.month).toBe(12);
    expect(esfand1403.days).toHaveLength(30);
    const esfand1404 = jalaliMonth(new Date(2026, 1, 25), new Date(2026, 1, 25));
    expect(esfand1404.month).toBe(12);
    expect(esfand1404.days).toHaveLength(29);
  });

  it("starts the week on Saturday", () => {
    // The grid's leading blanks must line the 1st up with the column of its
    // actual weekday: Saturday is column 0, Friday is column 6.
    expect(FA_WEEKDAYS).toHaveLength(7);
    for (let offset = 0; offset < 400; offset += 1) {
      const day = new Date(2026, 0, 1 + offset);
      const month = jalaliMonth(day, day);
      const first = month.days[0].date;
      // JS getDay(): 0=Sunday … 6=Saturday → Persian column is (getDay()+1)%7.
      expect(month.leadingBlanks, first.toDateString()).toBe((first.getDay() + 1) % 7);
    }
  });

  it("marks today", () => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const month = jalaliMonth(today, today);
    expect(month.days.filter((d) => d.isToday)).toHaveLength(1);
  });
});

describe("shiftJalaliMonth", () => {
  it("wraps across the year boundary", () => {
    // Anchored on a known Esfand rather than an assumed date: the whole point of
    // this test is the wrap, and it must not also depend on a second assumption.
    const esfand1404 = jalaliMonth(new Date(2026, 1, 25), new Date(2026, 1, 25));
    expect(esfand1404.month).toBe(12);
    const anchor = esfand1404.days[5].date;
    const month = jalaliMonth(shiftJalaliMonth(anchor, 1), new Date(2026, 1, 25));
    expect(month.month).toBe(1);
    expect(month.year).toBe(esfand1404.year + 1);
  });

  it("round-trips", () => {
    const anchor = new Date(2026, 5, 10);
    const there = shiftJalaliMonth(anchor, 7);
    const back = shiftJalaliMonth(there, -7);
    expect(jalaliMonth(back, back).month).toBe(jalaliMonth(anchor, anchor).month);
    expect(jalaliMonth(back, back).year).toBe(jalaliMonth(anchor, anchor).year);
  });

  it("always lands on day 1", () => {
    const shifted = shiftJalaliMonth(new Date(2026, 5, 10), 3);
    const month = jalaliMonth(shifted, shifted);
    const entry = month.days.find((d) => d.date.getTime() === shifted.getTime());
    expect(entry?.day).toBe(1);
  });
});

describe("faMonthTitle", () => {
  it("names the month in Persian, with a year that has no thousands separator", () => {
    const anchor = new Date(2026, 2, 21);
    const { year } = viaIntl(new Date(Date.UTC(2026, 2, 21)));
    const title = faMonthTitle(anchor);
    // «۱٬۴۰۵» is what faNum would produce for a year and it reads as a quantity.
    expect(title).not.toContain("٬");
    expect(title).toContain(String(year).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]));
  });
});
