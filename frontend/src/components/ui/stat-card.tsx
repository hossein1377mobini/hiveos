import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"
import type { StatusTone } from "@/lib/status"

const toneRing: Record<StatusTone, string> = {
  neutral: "bg-secondary text-muted-foreground",
  info: "bg-info-bg text-info",
  success: "bg-success-bg text-success",
  warning: "bg-warning-bg text-warning",
  error: "bg-error-bg text-error",
  teal: "bg-teal-soft text-teal",
  amber: "bg-amber-soft text-amber",
  violet: "bg-violet-soft text-violet",
}

/**
 * KPI tile used by the admin overview, the usage page and the knowledge header.
 * Replaces the hand-built stat blocks that each carried their own padding,
 * label size and number formatting. [D14/B1]
 */
export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "neutral",
  trend,
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: LucideIcon
  tone?: StatusTone
  /** Optional delta line, e.g. «۱۲٪ بیشتر از هفتهٔ گذشته». */
  trend?: ReactNode
  className?: string
}) {
  return (
    <div
      data-slot="stat-card"
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-card border border-border bg-card p-4 shadow-card",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-micro font-bold text-muted-foreground">{label}</span>
        {Icon && (
          <span
            aria-hidden
            className={cn(
              "flex size-7 shrink-0 items-center justify-center rounded-control",
              toneRing[tone],
            )}
          >
            <Icon className="size-4" />
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <span data-numeric className="text-display leading-none text-foreground">
          {value}
        </span>
        {hint && <span className="text-micro text-muted-foreground">{hint}</span>}
        {trend && <span className="text-micro text-muted-foreground">{trend}</span>}
      </div>
    </div>
  )
}
