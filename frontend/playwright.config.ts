import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end gate. [F3]
 *
 * vitest covers components in jsdom, which cannot tell you whether the app
 * actually boots: jsdom has no layout, no real navigation and no fetch to a
 * live origin. These tests run the built bundle in a real browser against a
 * stub API, so the things unit tests structurally cannot see are covered -
 * the router resolving a URL, the RTL shell laying out, a form submitting and
 * navigating, and the login redirect on an expired session.
 *
 * The API is stubbed at the network layer rather than with a mock server: the
 * backend owns its own contract tests, and the point here is the client.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    // localhost, not 127.0.0.1: vite binds the v6 loopback by default, so the
    // v4 literal is refused on some machines while the name resolves fine.
    baseURL: "http://localhost:4173",
    trace: "on-first-retry",
    locale: "fa-IR",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // An on-prem build machine usually has a browser and often no route to
        // playwright's CDN. Using the installed Chrome means the e2e gate runs
        // there instead of being skipped - and CI downloads the pinned build,
        // because HIVEOS_E2E_CHANNEL is unset there.
        channel: process.env.HIVEOS_E2E_CHANNEL || undefined,
      },
    },
  ],
  // The real build, served the way nginx serves it (SPA fallback included).
  webServer: {
    command: "npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173/login",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
