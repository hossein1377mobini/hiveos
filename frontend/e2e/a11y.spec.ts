import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

/**
 * axe-core against the real built app, route by route.
 *
 * The vitest a11y test runs axe in jsdom, which has no layout: it cannot see
 * colour contrast, and it cannot see that a <main> is nested inside another
 * <main> or that the nine sidebar links sit outside every landmark. Those were
 * real defects found only here. This suite is the browser half of the
 * three-layer checking the design-system sources call for: automated scanning
 * in CI (this file), manual keyboard passes, screen-reader passes.
 */

const READY = {
  organization_status: "active",
  expired: false,
  workspace_ready: true,
  brain_ready: true,
  knowledge_source: null,
  subscription: { plan: "pro", expires_at: "2027-01-01T00:00:00Z", expired: false },
  identity: { user_name: "manager.ar", organization_name: "شرکت آریا", plan_label: "pro" },
};

const SYSTEM_STATUS = {
  health: "green",
  generated_at: "2026-09-14T00:00:00Z",
  uptime_seconds: 100,
  environment: "dev",
  app_name: "HiveOS",
  db: { state: "up", migration_head: "0023", expected_head: "0023", migrations_ok: true, latency_ms: 1, size_bytes: 1, connections: 3 },
  counters: {
    organizations: 2, active_organizations: 2, users: 3, memberships: 3, active_sessions: 1,
    admin_sessions: 1, assets: 5, failed_assets: 0, wallets: 2, credit_total: 100,
    pending_charge_requests: 0, executions: 9, failed_executions: 0, messages: 20, audit_rows: 40,
  },
  last_audit_at: null,
  jobs: { open: 0, by_status: {} },
  process: { pid: 1, started_at: "2026-09-14T00:00:00Z", threads: 8 },
  host: { load: [0.1, 0.1, 0.1], disk: { total: 1, used: 1, free: 1, percent: 1 } },
  llm_provider: "openai",
  sms_provider: "kavenegar",
  embedding_provider: "openai",
  services: { api: "up", scheduler: "up", backup: "ok" },
};

/**
 * /admin/monitoring/host payload.
 *
 * OperationsView reads uptime, cpu, memory, disk and top_processes without
 * guards, so a stub that omits them throws and the route renders the error
 * boundary instead of the page under test.
 */
const HOST = {
  cpu: { percent: 5, model: "x", cores: 4, load: { "1m": 0.1, "5m": 0.1, "15m": 0.1 } },
  memory: { percent: 20, used_bytes: 1, total_bytes: 2 },
  disk: { mounts: [{ mount: "/", percent: 30, used_bytes: 1, total_bytes: 2 }] },
  network: { rx_bytes_per_s: 1, tx_bytes_per_s: 1 },
  uptime: { uptime_seconds: 1234 },
  top_processes: [{ pid: 1, name: "x", rss_bytes: 1, cpu_percent: 1 }],
};

/** Envelope a real handler returns; the panel is unforgiving about its shape. */
const ENVELOPE = (data: unknown) => JSON.stringify({ success: true, data, message: null });

const ROUTES = [
  "/chat",
  "/knowledge",
  "/wallet",
  "/usage",
  "/subscription",
  "/admin",
  "/admin/organizations",
  "/admin/billing",
  "/admin/operations",
  "/admin/ai",
  "/admin/events",
  "/admin/system",
];

for (const route of ROUTES) {
  test(`no accessibility violations on ${route}`, async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("hiveos.session", "e2e-token");
      sessionStorage.setItem("hiveos.admin", "e2e-admin-token");
    });
    await page.route("**/api/**", async (route_) => {
      const path = new URL(route_.request().url()).pathname;
      // /system-status must carry db/jobs/counters: the panel reads them
      // unguarded, and a thin stub makes it look like a product crash.
      const data = path.endsWith("/system-status")
        ? SYSTEM_STATUS
        : path.endsWith("/monitoring/host")
          ? HOST
          : path.endsWith("/auth/onboarding-status")
            ? READY
            : { items: [], total: 0, total_count: 0, page: 1, page_size: 50, has_more: false, usage: [], balance: 0 };
      await route_.fulfill({ status: 200, contentType: "application/json", body: ENVELOPE(data) });
    });

    await page.goto(route);
    await page.waitForTimeout(800);
    await page.addScriptTag({ content: axeSource });
    const violations = await page.evaluate(async () => {
      // @ts-expect-error injected at runtime by addScriptTag above
      const result = await window.axe.run(document, { resultTypes: ["violations"] });
      return result.violations.map((v: { id: string; impact: string | null; nodes: unknown[] }) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.length,
      }));
    });

    expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
  });
}
