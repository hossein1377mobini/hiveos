import { useState } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DateRangePicker, EMPTY_RANGE, type DateRange } from "./date-range-picker";
import { renderWithRouter } from "@/test/render";

/**
 * The Jalali picker is the one date control in the product, so its behaviour is
 * pinned here rather than through every page that uses it.
 *
 * The component is controlled, so the tests drive it through a stateful host —
 * clicking a second day only means anything if the first click actually moved
 * the value, which is the parent's job.
 */
function Harness({
  initial = EMPTY_RANGE,
  onChange,
}: {
  initial?: DateRange;
  onChange?: (next: DateRange) => void;
}) {
  const [value, setValue] = useState<DateRange>(initial);
  return (
    <DateRangePicker
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

function setup(initial: DateRange = EMPTY_RANGE) {
  const onChange = vi.fn();
  renderWithRouter(<Harness initial={initial} onChange={onChange} />);
  return { onChange };
}

/** The day cells, in order — the only buttons whose whole label is a number. */
function dayCells() {
  return within(screen.getByTestId("date-range-panel"))
    .getAllByRole("button")
    .filter((button) => /^[۰-۹]+$/.test(button.textContent ?? ""));
}

describe("DateRangePicker", () => {
  it("shows every day of a Jalali month, in Persian digits", () => {
    setup();
    fireEvent.click(screen.getByTestId("date-range-trigger"));
    const panel = screen.getByTestId("date-range-panel");
    // Farvardin has 31 days; the label must be a Persian month name.
    expect(screen.getByTestId("month-title").textContent).toMatch(
      /فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند/,
    );
    const dayButtons = within(panel)
      .getAllByRole("button")
      .filter((button) => /^[۰-۹]+$/.test(button.textContent ?? ""));
    expect(dayButtons.length).toBeGreaterThanOrEqual(29);
    expect(dayButtons.length).toBeLessThanOrEqual(31);
    // No Latin digits anywhere in the grid.
    expect(panel.textContent).not.toMatch(/[0-9]/);
  });

  it("moves to the previous month and back", () => {
    setup();
    fireEvent.click(screen.getByTestId("date-range-trigger"));
    const before = screen.getByTestId("month-title").textContent;
    fireEvent.click(screen.getByRole("button", { name: "ماه قبل" }));
    const previous = screen.getByTestId("month-title").textContent;
    expect(previous).not.toBe(before);
    fireEvent.click(screen.getByRole("button", { name: "ماه بعد" }));
    expect(screen.getByTestId("month-title").textContent).toBe(before);
  });

  it("selects a start then an end and reports the range", () => {
    const { onChange } = setup();
    fireEvent.click(screen.getByTestId("date-range-trigger"));
    const days = dayCells();
    fireEvent.click(days[4]);
    // First click only sets the start; the panel stays open for the end.
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].from).toBeTruthy();
    expect(onChange.mock.calls[0][0].to).toBeNull();
    fireEvent.click(dayCells()[9]);
    expect(onChange).toHaveBeenCalledTimes(2);
    const range = onChange.mock.calls[1][0];
    expect(range.from && range.to).toBeTruthy();
    expect(range.from <= range.to).toBe(true);
  });

  it("swaps the bounds when the end is picked before the start", () => {
    // A reversed range would return nothing and look like "no data".
    const { onChange } = setup();
    fireEvent.click(screen.getByTestId("date-range-trigger"));
    fireEvent.click(dayCells()[10]);
    fireEvent.click(dayCells()[3]);
    const range = onChange.mock.calls[1][0];
    expect(range.from <= range.to).toBe(true);
  });

  it("applies a preset in one click", () => {
    const { onChange } = setup();
    fireEvent.click(screen.getByTestId("date-range-trigger"));
    fireEvent.click(screen.getByRole("button", { name: "۷ روز" }));
    const range = onChange.mock.calls[0][0];
    // "۷ روز" is a seven-calendar-day window ending today, counting today. The
    // bounds therefore span six calendar days, and the window contains today.
    const start = new Date(range.from);
    const end = new Date(range.to);
    start.setHours(0, 0, 0, 0);
    end.setHours(0, 0, 0, 0);
    expect(Math.round((end.getTime() - start.getTime()) / 86_400_000)).toBe(6);

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    expect(end.getTime()).toBe(today.getTime());
    expect(start.getTime()).toBeLessThanOrEqual(today.getTime());
  });

  it("clears back to the unbounded state", () => {
    const { onChange } = setup({ from: "2026-01-01T00:00:00Z", to: "2026-01-05T00:00:00Z" });
    fireEvent.click(screen.getByTestId("date-range-trigger"));
    fireEvent.click(screen.getByRole("button", { name: "پاک کردن" }));
    expect(onChange).toHaveBeenCalledWith(EMPTY_RANGE);
  });

  it("summarises the current range on the trigger", () => {
    renderWithRouter(
      <DateRangePicker
        value={{ from: "2026-01-01T00:00:00Z", to: "2026-01-05T00:00:00Z" }}
        onChange={() => {}}
      />,
    );
    const trigger = screen.getByTestId("date-range-trigger");
    expect(trigger.textContent).toContain("از");
    expect(trigger.textContent).toContain("تا");
    expect(trigger.textContent).not.toMatch(/[0-9]/);
  });
});
