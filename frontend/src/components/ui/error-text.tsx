import { AlertCircleIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Inline error text — the one way this codebase reports a failed action.
 *
 * v0.1 had three spellings of the same thing: a bare <p> in some views, a
 * role="alert" <p> in others, and a full Banner in a third. A screen reader
 * announced the failures it happened to know about and stayed silent for the
 * rest, which is worse than never announcing them: the operator learns to trust
 * silence. This wrapper always carries role="alert" and always reads the same
 * way. [E4]
 *
 * Banner stays for page-level messages that need a title and an action; this is
 * for "the last thing you clicked did not work".
 */
export function ErrorText({
  children,
  className,
  ...props
}: React.ComponentProps<"p">) {
  if (!children) return null
  return (
    <p
      role="alert"
      data-slot="error-text"
      className={cn("flex items-start gap-1.5 text-caption text-error", className)}
      {...props}
    >
      <AlertCircleIcon aria-hidden className="mt-0.5 size-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  )
}
