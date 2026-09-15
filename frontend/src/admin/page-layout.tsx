import type { ReactNode } from "react"

import { cn } from "../lib/utils"
import { Spinner } from "../components/ui/spinner"

/**
 * Shared layout primitives for every admin workspace.
 *
 * The PO's report was that the admin pages did not read as one product: each
 * view invented its own header row, its own gap between the page title and the
 * content, and its own loading sentence ("در حال دریافت وضعیت…" here, "در حال
 * بارگذاری…" there, a bare skeleton somewhere else). The shell owns the page
 * heading, so what was left to each view was a section heading and a rhythm,
 * and every view chose a different one.
 *
 * These live under src/admin/ rather than src/components/ui/ only because that
 * directory is owned by another change in flight; they are generic enough to
 * belong there and should be promoted (see the handover note).
 *
 * Every heading here is an h2 and uses --text-heading, the "section or card
 * title" step of DESIGN-SYSTEM.md §3. The shell already renders the workspace
 * name as the page h1, so a second h1 would be a duplicate and an h3 would skip
 * a level — which axe reports as a heading-order violation.
 */

/** A section introduction: title, optional explanation, optional actions. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="grid gap-1">
        <h2 className="text-heading">{title}</h2>
        {description && (
          <p className="max-w-prose text-caption leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** The h2 on its own, for a heading that heads nothing but a list. */
export function SectionHeading({
  children,
  count,
  className,
}: {
  children: ReactNode
  count?: number
  className?: string
}) {
  return (
    <h2 className={cn("flex items-baseline gap-2 text-heading", className)}>
      {children}
      {count !== undefined && count > 0 && (
        <span data-numeric className="text-micro font-normal text-muted-foreground">
          ({count})
        </span>
      )}
    </h2>
  )
}

/**
 * One labelled block of the workspace: an optional heading, an optional
 * explanation, and the content with the single gap every view now shares.
 */
export function Section({
  title,
  description,
  actions,
  className,
  bodyClassName,
  children,
}: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
  bodyClassName?: string
  children: ReactNode
}) {
  return (
    <div className={cn("grid gap-3", className)}>
      {(title || description || actions) && (
        <PageHeader title={title} description={description} actions={actions} />
      )}
      <div className={cn("grid gap-3", bodyClassName)}>{children}</div>
    </div>
  )
}

/**
 * The one loading treatment. v0.1 used a different sentence per view and no
 * live region anywhere, so a screen reader read the page as empty until the
 * data happened to arrive.
 */
export function LoadingPanel({
  label = "در حال بارگذاری…",
  className,
}: {
  label?: string
  className?: string
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("flex items-center justify-center gap-2 py-10", className)}
    >
      <Spinner className="text-muted-foreground" />
      <span className="text-caption text-muted-foreground">{label}</span>
    </div>
  )
}
