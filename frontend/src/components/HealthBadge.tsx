import { useEffect, useState } from "react"

import { Badge } from "./ui/badge"
import { Spinner } from "./ui/spinner"

type HealthState =
  | { status: "checking" }
  | { status: "ok"; environment: string }
  | { status: "unreachable" }

// Liveness contract from T-S0-2: GET /api/health → {status, environment, version}.
// Going through the dev proxy, a green badge here proves the frontend→API wiring
// end to end. The version field stays out of the UI (technical detail, terminology §7).
async function fetchHealth(signal: AbortSignal): Promise<HealthState> {
  try {
    const response = await fetch("/api/health", { signal })
    if (!response.ok) {
      return { status: "unreachable" }
    }
    const body = (await response.json()) as { status?: string; environment?: string }
    if (body.status !== "ok") {
      return { status: "unreachable" }
    }
    return { status: "ok", environment: body.environment ?? "unknown" }
  } catch {
    return { status: "unreachable" }
  }
}

export function HealthBadge() {
  const [health, setHealth] = useState<HealthState>({ status: "checking" })

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal).then(setHealth)
    return () => controller.abort()
  }, [])

  if (health.status === "checking") {
    return (
      <Badge variant="secondary" role="status" className="px-3 py-1 text-sm">
        <Spinner data-icon="inline-start" />
        در حال بررسی سلامت سرویس…
      </Badge>
    )
  }
  if (health.status === "unreachable") {
    return (
      <Badge variant="outline" role="status" className="border-error-border bg-error-bg px-3 py-1 text-sm text-error">
        سرویس در دسترس نیست
      </Badge>
    )
  }
  return (
    <Badge variant="outline" role="status" className="border-success-border bg-success-bg px-3 py-1 text-sm text-success">
      متصل — محیط {health.environment}
    </Badge>
  )
}
