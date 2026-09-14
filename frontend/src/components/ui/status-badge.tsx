import { cva, type VariantProps } from "class-variance-authority"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

/**
 * HiveOS status chip — the domain tones of design-system §2.3 layered on the
 * official Badge. Rendering the official component (never a hand-rolled span)
 * keeps radius, font weight, icon sizing and RTL behaviour in one place; only
 * the colour role is added here.
 */
const statusBadgeVariants = cva("", {
  variants: {
    tone: {
      neutral: "border-border bg-secondary text-muted-foreground",
      info: "border-info-border bg-info-bg text-info",
      success: "border-success-border bg-success-bg text-success",
      warning: "border-warning-border bg-warning-bg text-warning",
      error: "border-error-border bg-error-bg text-error",
      teal: "border-transparent bg-teal-soft text-teal",
      amber: "border-transparent bg-amber-soft text-amber",
      violet: "border-transparent bg-violet-soft text-violet",
    },
  },
  defaultVariants: { tone: "neutral" },
})

export interface StatusBadgeProps
  extends React.ComponentProps<typeof Badge>,
    VariantProps<typeof statusBadgeVariants> {
  /** Leading status dot (mockup §۱۰ badge.dot). */
  dot?: boolean
}

export function StatusBadge({
  className,
  tone,
  dot = false,
  children,
  ...props
}: StatusBadgeProps) {
  return (
    <Badge
      data-slot="status-badge"
      variant="outline"
      className={cn("px-2.5 py-[3px] font-bold", statusBadgeVariants({ tone }), className)}
      {...props}
    >
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </Badge>
  )
}

export { statusBadgeVariants }
