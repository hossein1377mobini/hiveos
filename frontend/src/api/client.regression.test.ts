import { afterEach, describe, expect, it, vi } from "vitest"

import { api, clearToken } from "./client"

/**
 * The 401 side effects of the shared API client.
 *
 * These exist because of a real defect: the client redirects a signed-out user
 * to /login on every 401, and the admin panel's identity probe answered 401 for
 * anonymous visitors - so /admin bounced to /login before it could render its
 * own login form. The panel was unreachable by URL.
 */

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ success: false, error: { code: "AUTH_REQUIRED", message: "x" } }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
    ),
  )
}

function stubLocation(pathname: string) {
  const assign = vi.fn()
  const original = window.location
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...original, pathname, assign },
  })
  return {
    assign,
    restore: () => Object.defineProperty(window, "location", { configurable: true, value: original }),
  }
}

afterEach(() => {
  clearToken()
  vi.unstubAllGlobals()
})

describe("api client 401 handling", () => {
  it("does not redirect away from the admin panel", async () => {
    stubFetch()
    const location = stubLocation("/admin")
    await expect(api("GET", "/auth/onboarding-status")).rejects.toBeTruthy()
    expect(location.assign).not.toHaveBeenCalled()
    location.restore()
  })

  it("does not redirect away from a nested admin view either", async () => {
    stubFetch()
    const location = stubLocation("/admin/organizations")
    await expect(api("GET", "/auth/onboarding-status")).rejects.toBeTruthy()
    expect(location.assign).not.toHaveBeenCalled()
    location.restore()
  })

  it("still sends an organization user to the login screen", async () => {
    stubFetch()
    const location = stubLocation("/chat")
    await expect(api("GET", "/chat/sessions")).rejects.toBeTruthy()
    expect(location.assign).toHaveBeenCalledWith("/login")
    location.restore()
  })
})

