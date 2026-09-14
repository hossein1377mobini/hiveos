import { createContext, useContext, useEffect, useState } from "react"

import { api } from "@/api/client"
import type { SessionIdentity } from "@/lib/session"

/**
 * Who is signed in, for the whole authenticated app.
 *
 * GET /auth/onboarding-status returns the identity block [H1], but it is read by
 * the bootstrap route while the shell is rendered by five sibling routes. Passing
 * it down as a prop would mean every route re-fetching it or the router threading
 * state through, so it is loaded once here and shared. [D10]
 *
 * The value is null while loading and on failure: the shell falls back to its
 * role label rather than showing an empty header, and a failed identity fetch
 * must never keep a signed-in user out of the app.
 */
const SessionIdentityContext = createContext<SessionIdentity | null>(null)

export function SessionIdentityProvider({
  children,
  initial = null,
}: {
  children: React.ReactNode
  /** Already-known identity, so the bootstrap answer is not fetched twice. */
  initial?: SessionIdentity | null
}) {
  const [identity, setIdentity] = useState<SessionIdentity | null>(initial)

  useEffect(() => {
    if (initial) return
    let cancelled = false
    void (async () => {
      try {
        const status = await api<{ identity?: SessionIdentity | null }>(
          "GET",
          "/auth/onboarding-status",
        )
        if (!cancelled) setIdentity(status.identity ?? null)
      } catch {
        // Deliberately silent: the header degrades to the role label and the
        // page itself reports its own load failures.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [initial])

  return (
    <SessionIdentityContext.Provider value={identity}>{children}</SessionIdentityContext.Provider>
  )
}

export function useSessionIdentity(): SessionIdentity | null {
  return useContext(SessionIdentityContext)
}
