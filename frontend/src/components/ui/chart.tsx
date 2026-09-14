import * as React from "react"

import { cn } from "@/lib/utils"
import { faNum } from "@/lib/dates"

/**
 * Charts, built as inline SVG rather than pulling in a charting library.
 *
 * A charting dependency (recharts, chart.js) is 90-400 kB and brings its own
 * colour system, its own tooltip and its own fonts - all of which would then
 * have to be overridden to match the token layer. Everything HiveOS needs from
 * a chart is a handful of shapes, so these components draw them directly and
 * take their colours from the semantic roles. That keeps the bundle budget, and
 * it means a chart cannot drift from the palette the rest of the product uses.
 *
 * Accessibility: every chart here is aria-hidden and is expected to sit next to
 * a real number or table. A chart alone is not an accessible representation of
 * data, and pretending otherwise (a bare aria-label with no table) is worse
 * than drawing it as decoration beside the figure it visualises.
 */

export interface Point {
  label: string
  value: number
}

const NEUTRAL_GRID = "var(--color-neutral-200)"

/**
 * Sparkline - a bare trend line for a KPI tile.
 *
 * No axes, no labels, no grid: it exists to answer "which way is this going"
 * at a glance, and the exact numbers sit next to it in the tile.
 */
export function Sparkline({
  points,
  className,
  tone = "accent",
  height = 40,
}: {
  points: number[]
  className?: string
  tone?: "accent" | "success" | "error" | "muted"
  height?: number
}) {
  const stroke = {
    accent: "var(--color-accent-500)",
    success: "var(--color-success)",
    error: "var(--color-error)",
    muted: "var(--color-neutral-400)",
  }[tone]

  if (points.length < 2) {
    // A single point has no trend to draw. A flat hairline is honest; a dot
    // would imply a measurement where there is only one.
    return (
      <div
        aria-hidden
        className={cn("w-full rounded-full", className)}
        style={{ height: 2, background: NEUTRAL_GRID }}
      />
    )
  }

  const width = 100
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const step = width / (points.length - 1)
  // 2px inset so a stroke at the extreme value is not clipped by the viewBox.
  const toY = (value: number) => 2 + (1 - (value - min) / span) * (height - 4)
  const line = points.map((value, index) => index * step + "," + toY(value)).join(" ")
  const area = "0," + height + " " + line + " " + width + "," + height

  return (
    <svg
      aria-hidden
      viewBox={"0 0 " + width + " " + height}
      preserveAspectRatio="none"
      className={cn("w-full", className)}
      style={{ height }}
    >
      <polygon points={area} fill={stroke} opacity={0.08} />
      <polyline
        points={line}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/**
 * BarChart - horizontal bars, one row per category.
 *
 * Horizontal rather than vertical on purpose: the labels are Persian event
 * names and model identifiers, which do not fit under a vertical bar without
 * rotation, and rotated Persian text is unreadable at these sizes.
 */
export function BarChart({
  data,
  className,
  valueLabel,
  max: maxProp,
}: {
  data: Point[]
  className?: string
  /** Rendered after the value. Pass "" to hide it. */
  valueLabel?: string
  max?: number
}) {
  if (data.length === 0) {
    return <p className="text-caption text-muted-foreground">داده‌ای برای نمایش نیست.</p>
  }
  const max = maxProp ?? Math.max(...data.map((entry) => entry.value), 1)

  return (
    <div className={cn("grid gap-2", className)}>
      {data.map((entry) => {
        const percent = Math.max(2, Math.round((entry.value / max) * 100))
        return (
          <div key={entry.label} className="grid gap-1">
            <div className="flex items-baseline justify-between gap-3 text-caption">
              <span className="mono min-w-0 truncate" dir="ltr">
                {entry.label}
              </span>
              <span data-numeric className="shrink-0 text-muted-foreground">
                {faNum(entry.value)}
                {valueLabel ? " " + valueLabel : ""}
              </span>
            </div>
            {/* A real element with a width, not an SVG: it reflows with the
                container for free and needs no viewBox arithmetic. */}
            <div
              className="h-2 w-full overflow-hidden rounded-full bg-neutral-100"
              role="img"
              aria-label={entry.label + ": " + faNum(entry.value)}
            >
              <div
                className="h-full rounded-full bg-accent-500"
                style={{ width: percent + "%" }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Donut - a part-of-whole ring.
 *
 * Used for status breakdowns (ready / processing / failed). Capped at the six
 * slices the palette defines; beyond that the caller should use a bar chart,
 * because more than six hues cannot stay distinguishable.
 */
export function Donut({
  data,
  className,
  size = 160,
}: {
  data: Array<Point & { tone: string }>
  className?: string
  size?: number
}) {
  const total = data.reduce((sum, entry) => sum + entry.value, 0)
  if (total <= 0) {
    return <p className="text-caption text-muted-foreground">داده‌ای برای نمایش نیست.</p>
  }

  const radius = 60
  const circumference = 2 * Math.PI * radius
  // Arc geometry is derived up front rather than accumulated inside the map:
  // a running `offset` mutated during render is a render side effect, and the
  // React compiler rules reject it outright.
  const arcs = data.map((entry, index) => {
    const dash = (entry.value / total) * circumference
    const start = data
      .slice(0, index)
      .reduce((sum, prior) => sum + (prior.value / total) * circumference, 0)
    return { ...entry, dash, start }
  })

  return (
    <div className={cn("flex items-center gap-5", className)}>
      <svg
        aria-hidden
        viewBox="0 0 160 160"
        width={size}
        height={size}
        className="shrink-0"
        style={{ transform: "rotate(-90deg)" }}
      >
        {arcs.map((arc) => (
          <circle
            key={arc.label}
            cx={80}
            cy={80}
            r={radius}
            fill="none"
            stroke={"var(" + arc.tone + ")"}
            strokeWidth={16}
            strokeDasharray={arc.dash + " " + (circumference - arc.dash)}
            strokeDashoffset={-arc.start}
          />
        ))}
      </svg>
      <ul className="grid gap-1.5 text-caption">
        {data.map((entry) => (
          <li key={entry.label} className="flex items-center gap-2">
            <span
              aria-hidden
              className="size-2.5 shrink-0 rounded-full"
              style={{ background: "var(" + entry.tone + ")" }}
            />
            <span className="min-w-0 truncate">{entry.label}</span>
            <span data-numeric className="ms-auto text-muted-foreground">
              {faNum(entry.value)}
            </span>
            <span data-numeric className="w-10 text-end text-micro text-muted-foreground">
              {faNum(Math.round((entry.value / total) * 100))}٪
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Agent-stage timeline.
 *
 * This is the one place the Cursor timeline pastels are used, which is exactly
 * what the design system scopes them to ("Used only in product UI - never as
 * system action colours"). The stages are the pipeline an asset actually goes
 * through, so the colours carry meaning rather than decoration.
 */
export const TIMELINE_STAGES = [
  { id: "queued", label: "در صف", tone: "var(--color-peach)" },
  { id: "processing", label: "در حال پردازش", tone: "var(--color-mint)" },
  { id: "review", label: "نیازمند بازبینی", tone: "var(--color-sky)" },
  { id: "ready", label: "آماده", tone: "var(--color-violet)" },
  { id: "failed", label: "ناموفق", tone: "var(--color-amber)" },
] as const

export function StageTimeline({
  counts,
  className,
}: {
  counts: Record<string, number>
  className?: string
}) {
  return (
    <ol className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {TIMELINE_STAGES.map((stage, index) => {
        const count = counts[stage.id] ?? 0
        return (
          <li key={stage.id} className="flex items-center gap-1.5">
            <span
              className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-micro font-bold text-neutral-800"
              style={{ background: stage.tone }}
            >
              {stage.label}
              <span data-numeric>{faNum(count)}</span>
            </span>
            {index < TIMELINE_STAGES.length - 1 && (
              <span aria-hidden className="text-neutral-400">
                ←
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

/**
 * KpiTile - a single figure with its trend.
 *
 * Wraps the three things a KPI needs to be readable rather than decorative:
 * the value, what it is, and which way it moved. A bare number with an arrow
 * and no baseline is the most common way a dashboard misleads.
 */
export function KpiTile({
  label,
  value,
  hint,
  trend,
  tone = "neutral",
  className,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  trend?: number[]
  tone?: "neutral" | "accent" | "success" | "error"
  className?: string
}) {
  const valueTone = {
    neutral: "text-foreground",
    accent: "text-accent-600",
    success: "text-success",
    error: "text-error",
  }[tone]

  return (
    <div className={cn("grid gap-1.5 rounded-card border border-border bg-card p-4", className)}>
      <span className="text-micro font-bold text-muted-foreground">{label}</span>
      <span data-numeric className={cn("text-display leading-none", valueTone)}>
        {value}
      </span>
      {hint && <span className="text-micro text-muted-foreground">{hint}</span>}
      {trend && trend.length > 1 && <Sparkline points={trend} tone={tone === "error" ? "error" : "accent"} />}
    </div>
  )
}
