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

/**
 * «ایجنت من» payloads.
 *
 * The page reads agent.memory.total and maps memories/tools without guards, so
 * the generic list fallback below would throw and the route would be scanning
 * an error boundary rather than the page.
 */
const AGENT = {
  id: "00000000-0000-0000-0000-000000000001",
  display_name: "دستیار من",
  // Still returned by GET /agent, but the page must not render an editor for
  // it: PATCH /agent accepts display_name only, so a persona control would be
  // one the server rejects. The stub keeps the field so the page is scanned
  // with the real payload shape.
  persona: "کوتاه و رسمی پاسخ بده.",
  status: "active",
  version: 2,
  allowed_tools: ["build_chart"],
  memory: { total: 1, by_kind: { preference: { count: 1, avg_weight: 1 } } },
};
const AGENT_MEMORY = {
  memories: [
    {
      id: "00000000-0000-0000-0000-000000000002",
      kind: "preference",
      content: "خروجی را همیشه فارسی بنویس.",
      weight: 1,
      hits: 3,
      misses: 0,
      active: true,
      created_at: "2026-09-14T00:00:00Z",
    },
  ],
};
/**
 * GET /agent/tools is read-only now and carries managed_by plus unrestricted,
 * so the page renders policy instead of checkboxes. Without these two keys the
 * page would fall into its "some tools are enabled" branch and never state
 * that an empty allowlist means every tool.
 */
const AGENT_TOOLS = {
  tools: [
    { name: "build_chart", description: "ساخت نمودار از داده", enabled: true, writes: true },
    { name: "build_report", description: "ساخت گزارش", enabled: false, writes: true },
  ],
  allowlist: ["build_chart"],
  unrestricted: false,
  managed_by: "organization",
};
const ADMIN_AGENTS = {
  agents: [
    {
      id: "00000000-0000-0000-0000-000000000001",
      organization_id: "00000000-0000-0000-0000-00000000000a",
      organization_name: "شرکت آریا",
      user_id: "00000000-0000-0000-0000-00000000000b",
      username: "manager.ar",
      display_name: "",
      status: "active",
      version: 2,
      allowed_tools: [],
      memory_count: 4,
      active_memory_count: 3,
      tool_calls: 7,
      tool_failures: 1,
      last_tool_at: "2026-09-14T00:00:00Z",
      last_active_at: "2026-09-14T00:00:00Z",
      created_at: "2026-09-01T00:00:00Z",
    },
  ],
  totals: { agents: 1, active: 1, organizations: 1 },
};

/** Envelope a real handler returns; the panel is unforgiving about its shape. */
const ENVELOPE = (data: unknown) => JSON.stringify({ success: true, data, message: null });

const ROUTES = [
  "/",
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
  "/admin/agents",
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
            : path.endsWith("/agent/memory")
              ? AGENT_MEMORY
              : path.endsWith("/agent/tools")
                ? AGENT_TOOLS
                : path.endsWith("/agent")
                  ? AGENT
                  : path.endsWith("/admin/agents")
                    ? ADMIN_AGENTS
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
