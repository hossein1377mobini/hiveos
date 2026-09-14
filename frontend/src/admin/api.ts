import { persianError } from "../api/errors"

/**
 * Admin transport.
 *
 * This lived inside AdminApp.tsx, so MonitoringTab had to import from the very
 * module that renders it — a cycle where importing the monitoring view pulled in
 * the whole panel, and refactoring either file risked a runtime TDZ error that
 * TypeScript cannot see. [A2]
 */
export const ADMIN_BASE = "/api/v1/admin"

export interface Envelope {
  success: boolean
  data?: unknown
  error?: { code: string; message: string }
}

/** Thrown when the admin session is gone, so the shell can log out. */
export class AdminSessionExpired extends Error {}

// The views each call adminApi from their own catch blocks; a dead session must
// log the whole panel out regardless of which view noticed it.
let sessionExpiredHandler: (() => void) | null = null

export function setAdminSessionExpiredHandler(handler: (() => void) | null): void {
  sessionExpiredHandler = handler
}

/** Reads one envelope response, keeping every server string out of the UI. */
export async function readEnvelope(response: Response): Promise<Envelope | null> {
  try {
    return (await response.json()) as Envelope
  } catch {
    return null
  }
}

export async function adminApi<T>(
  token: string,
  method: "GET" | "PUT" | "POST" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(ADMIN_BASE + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  // F: an expired/revoked admin token answers 403 (and a proxy 502+ answers
  // HTML) - both used to surface as "Unexpected token" or a silently dead tab.
  const payload = await readEnvelope(response)
  if (response.status === 403 && payload?.error?.code === "ADMIN_FORBIDDEN") {
    sessionExpiredHandler?.()
    throw new AdminSessionExpired("نشست مدیر منقضی شده است.")
  }
  if (payload === null) {
    throw new Error(persianError("CLIENT_BAD_RESPONSE", response.status))
  }
  if (!payload.success || payload.data === undefined) {
    // PO request: the panel never shows the server's English developer text.
    throw new Error(
      persianError(payload.error?.code ?? "UNKNOWN", response.status, payload.error?.message),
    )
  }
  return payload.data as T
}
