import { StatusBadge } from "@/components/ui/status-badge"
import { statusOf, type StatusDomain } from "@/lib/status"

/**
 * Renders a backend status value through the shared registry.
 *
 * v0.1 carried three separate status-to-label maps — one in AdminApp, one in
 * MonitoringTab, one in the app pages — and each had its own idea of what a
 * given value was called and what colour it deserved. The same asset could read
 * «آماده» in one screen and «فعال» in another. One registry, one component. [B4]
 *
 * An unrecognised value renders as itself with a neutral tone rather than
 * disappearing: a new backend status must still be visible to an operator.
 */
export function DomainStatus({
  domain,
  value,
  dot = true,
  className,
}: {
  domain: StatusDomain
  value: string | null | undefined
  dot?: boolean
  className?: string
}) {
  const status = statusOf(domain, value)
  return (
    <StatusBadge tone={status.tone} dot={dot} className={className} title={status.hint}>
      {status.label}
    </StatusBadge>
  )
}
