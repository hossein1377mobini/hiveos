import { useCallback, useEffect, useRef, useState } from "react"
import { TriangleAlertIcon } from "lucide-react"

import { Button } from "../components/ui/button"
import { adminApi, AdminSessionExpired } from "./api"

/** Shared retry affordance: a failed panel view offers «تلاش مجدد». */
export function Retry({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      data-testid="admin-retry"
      className="flex flex-wrap items-center gap-3 rounded-control border border-error-border bg-error-bg px-3 py-2.5"
    >
      <TriangleAlertIcon aria-hidden className="size-4 shrink-0 text-error" />
      <p className="text-caption font-bold text-error">{message}</p>
      <Button variant="outline" size="sm" className="ms-auto rounded-control" onClick={onRetry}>
        تلاش مجدد
      </Button>
    </div>
  )
}

/**
 * Polling hook for live panel data.
 *
 * The panel shows server state "at a glance", not a snapshot from page-load
 * time, so every live view polls while it is on screen. Two behaviours matter:
 * a failed refresh must not blank out data that is already on screen (a brief
 * network blip should not empty the dashboard), and the interval must be cleared
 * on unmount so a closed view stops hitting the API.
 */
export function useLive<T>(token: string, path: string, everyMs: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  // Read through a ref so the polling effect does not restart on every tick.
  const hasData = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await adminApi<T>(token, "GET", path)
      hasData.current = true
      setData(next)
      setError(null)
      setUpdatedAt(new Date())
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      if (!hasData.current) setError(err instanceof Error ? err.message : "دریافت اطلاعات ناموفق بود.")
    } finally {
      setLoading(false)
    }
  }, [token, path])

  // `load` is a dependency now instead of a suppressed one: the effect restarts
  // the poll whenever the token or path changes, which is what made the old
  // disable comment dangerous — a stale closure kept polling the previous
  // endpoint after an operator switched organisation.
  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), everyMs)
    return () => clearInterval(id)
  }, [load, everyMs])

  return { data, error, loading, updatedAt, reload: load }
}
