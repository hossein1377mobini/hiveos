import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminApp from "./AdminApp";

afterEach(() => {
  sessionStorage.removeItem("hiveos.admin");
  vi.unstubAllGlobals();
});

describe("Admin panel", () => {
  it("requires login first", () => {
    render(<AdminApp />);
    expect(screen.getByText("پنل مدیریت HiveOS")).toBeInTheDocument();
    expect(screen.getByLabelText("نام کاربری")).toBeInTheDocument();
  });

  it("shows an error on wrong credentials", async () => {
    const fn = vi.fn(async () =>
      new Response(
        JSON.stringify({
          success: false,
          error: { code: "INVALID_CREDENTIALS", message: "Wrong system admin credentials." },
        }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fn);
    render(<AdminApp />);
    await screen.findByLabelText("نام کاربری");
  });

  it("opens settings tab with the four keys after login", async () => {
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) {
        return new Response(
          JSON.stringify({ success: true, data: { token: "adm-token", role: "system_admin" } }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      const key = url.replace("/api/v1/admin/settings/", "");
      const presets: Record<string, unknown> = {
        providers_pricing: {},
        models_allowlist: {},
        pipeline: {},
        prompt_template: {},
      };
      return new Response(
        JSON.stringify({ success: true, data: presets[key] ?? {} }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fn);
    render(<AdminApp />);
    // login form appears first (no stored token)
    expect(await screen.findByText("پنل مدیریت HiveOS")).toBeInTheDocument();
  });

  it("renders the live status snapshot and the event log", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/logs")
        ? {
            total: 1,
            limit: 50,
            offset: 0,
            logs: [
              {
                id: "1",
                event: "knowledge-source.created",
                level: "info",
                entity_type: "knowledge_source",
                detail: null,
                created_at: "2026-09-16T10:00:00Z",
                organization_name: "شرکت نمونه",
                actor_username: null,
              },
            ],
            server_log: { path: null, available: false, lines: [] },
          }
        : {
            health: "degraded",
            uptime_seconds: 3600,
            environment: "dev",
            db: { state: "up", migration_head: "0023", migrations_ok: true, latency_ms: 3.5, connections: 4 },
            counters: { organizations: 2, assets: 7 },
            jobs: { open: 1, by_status: { queued: 1 } },
            process: { pid: 42, threads: 8 },
            host: { load: { "1m": null, "5m": null, "15m": null }, disk: { root: "/", total_bytes: 100, free_bytes: 40, uploads_bytes: 10 } },
            llm_provider: "mock",
            sms_provider: "mock",
            embedding_provider: "mock",
            services: { api: "up" },
          };
      return new Response(JSON.stringify({ success: true, data: body }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fn);
    render(<AdminApp />);
    fireEvent.click(await screen.findByRole("button", { name: "وضعیت سامانه" }));
    // live numbers with a Persian health label
    expect(await screen.findByTestId("overall")).toHaveTextContent("نیازمند بررسی");
    expect(screen.getByTestId("jobs-open")).toHaveTextContent("1");

    // ...and the logs tab lists the audit trail
    fireEvent.click(screen.getByRole("button", { name: "رویدادها" }));
    expect(await screen.findByText("knowledge-source.created")).toBeInTheDocument();
    expect(await screen.findByText("شرکت نمونه")).toBeInTheDocument();
  });
});

describe("Monitoring tab", () => {
  const hostPayload = {
    cpu: { percent: 23.5, cores: 6, model: "AMD EPYC", load: { "1m": 0.4, "5m": 0.3, "15m": 0.2 }, per_core: [20, 25] },
    memory: { total_bytes: 12 * 1024 ** 3, used_bytes: 4 * 1024 ** 3, available_bytes: 8 * 1024 ** 3, percent: 33.3, swap_total_bytes: 2 * 1024 ** 3, swap_used_bytes: 0 },
    disk: { mounts: [{ path: "/", total_bytes: 72 * 1024 ** 3, used_bytes: 11 * 1024 ** 3, free_bytes: 61 * 1024 ** 3, percent: 15.2 }], io: [] },
    network: { interfaces: [{ name: "eth0", rx: 1024, tx: 512 }] },
    uptime: { uptime_seconds: 90000 },
    top_processes: [{ pid: 10, name: "uvicorn backend.main:app", rss_bytes: 90 * 1024 ** 2 }],
  };
  const aiPayload = {
    state: "ok",
    api_key_masked: "...25SV",
    configured_models: { chat: "deepseek-v4.1-flash", embedding: "text-embedding-3-large", rerank: "cohere-rerank-v4.0-fast" },
    credit: { remaining_irt: 1926851.85, remaining_unit: 0, account_tier: 3, exchange_rate: 228650 },
    usage: { transactions: 939, tokens_total: 120612078, tokens_cached: 93699748, cost_unit: 4.54, cost_irt: 2601.64 },
    usage_by_model: [{ model: "deepseek-v4.1-flash", transactions: 920, tokens: 120609165, cost_unit: 4.53 }],
    packages: [
      {
        name: "وایب کُدر روزانه حرفه‌ای",
        remaining_irt: 1913040.57,
        days_left: 0.86,
        models: ["deepseek-v4.1-flash", "glm-5.3"],
      },
    ],
    covered_models: ["deepseek-v4.1-flash", "glm-5.3"],
  };

  // The tab loads a backup state alongside the host and AI snapshots, so the
  // stub answers that route too rather than falling through to the check slot.
  const backupPayload = {
    state: "ok",
    files: 7,
    latest: {
      name: "hiveos-20260913-033001.dump",
      size_bytes: 82_534,
      age_hours: 13.4,
      created_at: "2026-09-13T03:30:01Z",
    },
  };

  function stub(payloads: { host?: unknown; ai?: unknown; check?: unknown; backup?: unknown }) {
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/monitoring/host")
        ? payloads.host
        : url.includes("/monitoring/ai")
          ? payloads.ai
          : url.includes("/system-status/backup")
            ? (payloads.backup ?? backupPayload)
            : payloads.check;
      return new Response(JSON.stringify({ success: true, data: body }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fn);
    return fn;
  }

  it("shows server resources as Persian gauges", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({ host: hostPayload, ai: aiPayload });
    render(<AdminApp />);
    fireEvent.click(await screen.findByRole("button", { name: "پایش سرور و هوش مصنوعی" }));
    expect(await screen.findByTestId("gauge-value-پردازنده")).toHaveTextContent("۲۳٫۵٪");
    expect(screen.getByTestId("gauge-value-حافظه")).toHaveTextContent("۳۳٫۳٪");
    expect(screen.getByTestId("gauge-value-فضای دیسک")).toHaveTextContent("۱۵٫۲٪");
  });

  it("shows the AI balance in Toman and flags an expiring package", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({ host: hostPayload, ai: aiPayload });
    render(<AdminApp />);
    fireEvent.click(await screen.findByRole("button", { name: "پایش سرور و هوش مصنوعی" }));
    expect(await screen.findByTestId("ai-balance")).toHaveTextContent("۱٬۹۲۶٬۸۵۲");
    // days_left 0.86 is inside the three-day window, so the PO gets a warning
    // rather than having to notice a small number on a card.
    expect(screen.getByTestId("ai-credit-warning")).toBeInTheDocument();
    expect(screen.getByText(/در این بسته هست/)).toBeInTheDocument();
  });

  it("explains a provider with no account API instead of showing an error", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({ host: hostPayload, ai: { state: "unsupported", reason: "NO_ACCOUNT_API", credit: null, usage: null, usage_by_model: [], packages: [], covered_models: [] } });
    render(<AdminApp />);
    fireEvent.click(await screen.findByRole("button", { name: "پایش سرور و هوش مصنوعی" }));
    expect(await screen.findByText(/امکان گزارش اعتبار را ارائه نمی‌دهد/)).toBeInTheDocument();
  });

  it("warns when the nightly backup has gone stale", async () => {
    // A cron that silently stopped is the failure the panel exists to catch:
    // otherwise the PO only learns there was no backup during a restore.
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({
      host: hostPayload,
      ai: aiPayload,
      backup: {
        state: "stale",
        files: 1,
        latest: {
          name: "hiveos-20260910-033001.dump",
          size_bytes: 80_000,
          age_hours: 74.2,
          created_at: "2026-09-10T03:30:01Z",
        },
      },
    });
    render(<AdminApp />);
    fireEvent.click(await screen.findByRole("button", { name: "پایش سرور و هوش مصنوعی" }));
    const card = await screen.findByTestId("backup-card");
    expect(card).toHaveTextContent("قدیمی");
    expect(within(card).getByTestId("backup-state")).toHaveTextContent("بررسی کنید");
    // The dump name is an internal identifier, not something to hide.
    expect(card).toHaveTextContent("hiveos-20260910-033001.dump");
  });

  it("surfaces a failing model check in Persian", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({
      host: hostPayload,
      ai: aiPayload,
      check: { ok: false, state: "failed", model: "gpt-5-mini", code: "LLM_PROVIDER_CREDIT", detail: "The provider account is out of credit." },
    });
    render(<AdminApp />);
    fireEvent.click(await screen.findByRole("button", { name: "پایش سرور و هوش مصنوعی" }));
    fireEvent.click(await screen.findByTestId("model-check-button"));
    const result = await screen.findByTestId("model-check-result");
    expect(result).toHaveTextContent("مدل پاسخ نداد");
    // the developer's English string must never reach the PO
    expect(result).not.toHaveTextContent("out of credit");
  });
});