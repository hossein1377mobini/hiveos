import { Loader2Icon } from "lucide-react"

/**
 * Shown while a lazily-loaded route chunk arrives. Deliberately the same shape
 * as the shell's own loading state so a cold start does not flash two different
 * layouts before the real page appears. [A6]
 */
export function RouteFallback({ label = "در حال بارگذاری…" }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-muted-foreground"
    >
      <Loader2Icon aria-hidden className="size-5 animate-spin" />
      <span className="text-caption">{label}</span>
    </div>
  )
}
