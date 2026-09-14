import { useMemo, useState } from "react"
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

import { Button } from "./button"
import { cn } from "@/lib/utils"
import { FA_WEEKDAYS, faDateShort, faMonthTitle, faNum, jalaliMonth, shiftJalaliMonth } from "@/lib/dates"

export interface DateRange {
  /** Inclusive ISO lower bound, or null for "no limit". */
  from: string | null
  /** Inclusive ISO upper bound, or null for "no limit". */
  to: string | null
}

export const EMPTY_RANGE: DateRange = { from: null, to: null }

/**
 * Persian (Jalali) date-range picker.
 *
 * The design system lists a Jalali picker as a requirement (§۳.۱) and v0.1 never
 * shipped one, so the audit trail could only be filtered by level — answering
 * "what did this organisation do last week" meant paging through everything. [D15]
 *
 * The month grid is plain buttons over the Jalali arithmetic in lib/dates, so
 * there is no date-library dependency to audit for an air-gapped install. It
 * renders inline rather than in a Popover because the codebase has no Popover
 * primitive and adding one for a single caller is not worth the surface area.
 *
 * Presets come first: they answer the common question in one click, and the grid
 * is there for the rest.
 */
export function DateRangePicker({
  value,
  onChange,
  className,
}: {
  value: DateRange
  onChange: (next: DateRange) => void
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState(() => new Date())
  const [picking, setPicking] = useState<"from" | "to">("from")

  const month = useMemo(() => jalaliMonth(anchor), [anchor])

  function pick(iso: string) {
    if (picking === "from") {
      // Picking a start after the current end would produce a range the operator
      // cannot explain, so the stale end is dropped rather than kept.
      onChange({ from: iso, to: value.to && iso <= value.to ? value.to : null })
      setPicking("to")
      return
    }
    onChange(value.from && iso < value.from ? { from: iso, to: value.from } : { from: value.from, to: iso })
    setPicking("from")
    setOpen(false)
  }

  function preset(days: number) {
    const to = new Date()
    to.setHours(23, 59, 59, 999)
    const from = new Date(to.getTime() - (days - 1) * 86_400_000)
    from.setHours(0, 0, 0, 0)
    onChange({ from: from.toISOString(), to: to.toISOString() })
    setOpen(false)
  }

  const label = value.from
    ? value.to && value.to !== value.from
      ? "از " + faDateShort(value.from) + " تا " + faDateShort(value.to)
      : faDateShort(value.from)
    : "همهٔ بازه‌ها"

  return (
    <div className={cn("relative", className)}>
      <Button
        variant="outline"
        size="sm"
        className="rounded-control"
        aria-expanded={open}
        data-testid="date-range-trigger"
        onClick={() => setOpen((previous) => !previous)}
      >
        <CalendarIcon className="size-3.5" />
        {label}
      </Button>

      {open && (
        <div
          data-testid="date-range-panel"
          className="absolute top-full z-40 mt-1 w-[320px] rounded-card border border-border bg-popover p-3 shadow-pop"
        >
          <div className="mb-2 flex flex-wrap gap-1.5">
            {[
              { label: "امروز", days: 1 },
              { label: "۷ روز", days: 7 },
              { label: "۳۰ روز", days: 30 },
              { label: "۹۰ روز", days: 90 },
            ].map((entry) => (
              <Button
                key={entry.days}
                variant="secondary"
                size="xs"
                className="rounded-control"
                onClick={() => preset(entry.days)}
              >
                {entry.label}
              </Button>
            ))}
          </div>

          <div className="mb-2 flex items-center justify-between">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="ماه قبل"
              onClick={() => setAnchor(shiftJalaliMonth(anchor, -1))}
            >
              <ChevronRightIcon className="size-4" />
            </Button>
            <span className="text-caption font-bold" data-testid="month-title">
              {faMonthTitle(anchor)}
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="ماه بعد"
              onClick={() => setAnchor(shiftJalaliMonth(anchor, 1))}
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
          </div>

          <div className="grid grid-cols-7 gap-1 text-center">
            {FA_WEEKDAYS.map((weekday) => (
              <span key={weekday} className="text-micro font-bold text-muted-foreground">
                {weekday}
              </span>
            ))}
            {Array.from({ length: month.leadingBlanks }, (_, index) => (
              <span key={"blank-" + index} />
            ))}
            {month.days.map((entry) => {
              const start = value.from ? value.from.slice(0, 10) : null
              const end = value.to ? value.to.slice(0, 10) : null
              const day = entry.iso.slice(0, 10)
              const selected = day === start || day === end
              const inRange = start !== null && end !== null && day > start && day < end
              return (
                <button
                  key={entry.iso}
                  type="button"
                  onClick={() => pick(entry.iso)}
                  aria-current={entry.isToday ? "date" : undefined}
                  className={cn(
                    "rounded-control py-1.5 text-caption transition-colors",
                    "hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    inRange && "bg-accent",
                    selected && "bg-primary font-bold text-primary-foreground",
                    entry.isToday && !selected && "font-bold text-primary",
                  )}
                >
                  {faNum(entry.day)}
                </button>
              )
            })}
          </div>

          <div className="mt-3 flex items-center justify-between border-t border-border pt-2">
            <span className="text-micro text-muted-foreground">
              {picking === "from" ? "روز شروع را انتخاب کنید" : "روز پایان را انتخاب کنید"}
            </span>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => {
                onChange(EMPTY_RANGE)
                setOpen(false)
              }}
            >
              پاک کردن
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
