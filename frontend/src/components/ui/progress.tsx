import * as React from "react"
import { cn } from "@/lib/utils"
import { Progress as ProgressPrimitive } from "radix-ui"

/**
 * Progress bar.
 *
 * Two defects were fixed here, both found while adding per-file preparation
 * percentages to the knowledge page:
 *
 * 1. `value` was destructured and then never forwarded to Radix's Root. Radix
 *    publishes `aria-valuenow`, `aria-valuetext` and `data-state` FROM that
 *    prop, so every progress bar in the product was a progressbar with no value
 *    - it announced itself and then said nothing. Passing it through is the
 *    whole fix.
 *
 * 2. The fill used a `translateX` transform, which is a PHYSICAL direction.
 *    This product is RTL-only, so the bar grew from the left, away from the edge
 *    the reader starts at. A percentage width fills from the inline-start, which
 *    is the right edge under `dir="rtl"`, so the same markup reads correctly and
 *    needs no direction-specific override.
 */
function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  // Clamp rather than trust the caller: a width of "110%" or "NaN%" is invisible
  // breakage, and a value arriving from a poll must not be able to corrupt the
  // bar. Matches what Radix itself does with an out-of-range value.
  const percent = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      value={percent}
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-primary/20",
        className
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className="h-full bg-primary transition-[width] duration-300 ease-out"
        style={{ width: `${percent}%` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
