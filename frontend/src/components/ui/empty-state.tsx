import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { cn } from "@/lib/utils"

/**
 * Every list, table and feed in the product has exactly one empty state
 * component now. [C2]
 *
 * v0.1 shipped ui/empty.tsx and never imported it; each page invented its own
 * "nothing here" paragraph instead, so tone and spacing differed everywhere.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon
  title: string
  description?: ReactNode
  /** Primary next step — an empty state without one is a dead end. */
  action?: ReactNode
  className?: string
}) {
  return (
    <Empty className={cn("border border-dashed border-border bg-neutral-25 py-14", className)}>
      <EmptyHeader className="gap-1.5">
        {Icon && (
          <EmptyMedia
            variant="icon"
            className="mb-3 size-12 rounded-control bg-secondary text-muted-foreground"
          >
            <Icon className="size-6" />
          </EmptyMedia>
        )}
        <EmptyTitle className="text-heading">{title}</EmptyTitle>
        {description && <EmptyDescription className="text-caption">{description}</EmptyDescription>}
      </EmptyHeader>
      {action && <EmptyContent className="max-w-none flex-row justify-center">{action}</EmptyContent>}
    </Empty>
  )
}
