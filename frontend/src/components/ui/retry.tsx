import { RefreshCwIcon } from "lucide-react"

import { Banner } from "@/components/ui/banner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * PO request 2026-09-12: a failed load must always offer a way forward — the
 * page shows the Persian reason and a «تلاش مجدد» button instead of an empty
 * screen the user cannot leave. Composed from Banner (→ official Alert) and the
 * official Button; no custom surface.
 */
export function RetryNotice({
  message,
  onRetry,
  busy = false,
  testId = "retry",
  compact = false,
}: {
  message: string
  onRetry: () => void
  busy?: boolean
  testId?: string
  compact?: boolean
}) {
  return (
    <Banner
      tone="error"
      data-testid={testId}
      className={cn(
        compact
          ? "items-center py-2.5"
          : "mx-auto w-full max-w-xl p-5 text-center shadow-card",
      )}
    >
      <div className={cn("font-bold", compact ? "flex flex-wrap items-center gap-3" : "flex flex-col gap-3")}>
        <p>{message}</p>
        <Button
          type="button"
          variant="outline"
          size={compact ? "xs" : "sm"}
          className={compact ? undefined : "self-center"}
          disabled={busy}
          onClick={onRetry}
        >
          <RefreshCwIcon data-icon="inline-start" />
          تلاش مجدد
        </Button>
      </div>
    </Banner>
  )
}
