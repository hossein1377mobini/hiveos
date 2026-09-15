import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "../api/client"

/**
 * Live app-side data: poll a GET endpoint while the screen is open.
 *
 * PO request (2026-09): "این تغییرات وضعیت‌ها باید آنلاین باشه و من ببینم
 * تغییرات رو" — the app used to show a snapshot taken when the page mounted, so
 * seeing a new status meant navigating away and back. That is the bug this hook
 * exists to remove.
 *
 * Why polling and not SSE. The backend has an SSE hub
 * (`backend/chat/streaming.py`) but nothing publishes to it: an opened stream
 * receives `stream.started` and then nothing. Polling a real endpoint is the
 * honest mechanism today, and it needs no new transport. If a publisher is ever
 * wired into the execution path, this hook is the single place to swap.
 *
 * Three behaviours are deliberate:
 *
 *  1. A failed refresh NEVER blanks data already on screen. A screen that goes
 *     empty on one dropped request looks like data loss; the operator then
 *     reloads and loses their place.
 *  2. Polling pauses while the tab is hidden and refetches once when it becomes
 *     visible — the moment the stale value would actually be read. A background
 *     tab must not poll forever.
 *  3. `path === null` disables polling without unmounting. Screens use this to
 *     poll fast only while something is in flight (a generation, an upload) and
 *     stop once everything has settled, instead of paying for a timer forever.
 */
export interface LiveState<T> {
  data: T | null
  error: string | null
  loading: boolean
  updatedAt: Date | null
  reload: () => Promise<void>
}

export function useLive<T>(path: string | null, everyMs: number): LiveState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  // Read through a ref so a successful load does not restart the poll loop.
  const hasData = useRef(false)

  const load = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      const next = await api<T>("GET", path)
      hasData.current = true
      setData(next)
      setError(null)
      setUpdatedAt(new Date())
    } catch (err) {
      // Keep whatever is on screen. Only a first, data-less failure is worth
      // showing as an error, because there is nothing else to look at.
      if (!hasData.current) setError(err instanceof Error ? err.message : "دریافت اطلاعات ناموفق بود.")
    } finally {
      setLoading(false)
    }
  }, [path])

  useEffect(() => {
    if (!path) return
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return
      void load()
    }
    void load()
    const id = setInterval(tick, everyMs)
    const onVisible = () => {
      if (!document.hidden) void load()
    }
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [load, everyMs, path])

  return { data, error, loading, updatedAt, reload: load }
}

/**
 * True while at least one item still has a status that is going to change.
 *
 * Callers pass the set of statuses that mean "still moving". Keeping it a
 * predicate rather than a fixed list lets each screen define what settled means
 * for its own rows, so the upload list and the ingestion list can disagree
 * without this helper knowing about either.
 */
export function anyPending<T>(rows: readonly T[] | null | undefined, isPending: (row: T) => boolean): boolean {
  if (!rows) return false
  return rows.some(isPending)
}
