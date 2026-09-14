import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminApp from "./AdminApp";
import { renderWithRouter } from "../test/render";

afterEach(() => {
  sessionStorage.removeItem("hiveos.admin");
  vi.unstubAllGlobals();
});

/**
 * The panel is routed now: every workspace has its own URL, so tests enter
 * through renderWithRouter and assert both the content and the address that
 * produces it. [A1/D3]
 */
function renderAdmin(route = "/admin") {
  return renderWithRouter(<AdminApp />, { route });
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify({ success: true, data }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Admin panel", () => {
  it("requires login first", () => {
    renderAdmin();
    expect(screen.getByText("پنل مدیریت HiveOS")).toBeInTheDocument();
    expect(screen.getByLabelText("نام کاربری")).toBeInTheDocument();
  });

  it("shows a Persian message on wrong credentials", async () => {
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
    renderAdmin();
    fireEvent.change(await screen.findByLabelText("نام کاربری"), { target: { value: "root" } });
    fireEvent.change(screen.getByLabelText("گذرواژه"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "ورود" }));
    const alert = await screen.findByTestId("admin-error");
    // The server's English developer text must never reach the operator.
    expect(alert).not.toHaveTextContent("Wrong system admin credentials");
  });

  it("lands on the overview after login and offers every workspace", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    vi.stubGlobal("fetch", vi.fn(async () => json({
      health: "green",
      uptime_seconds: 3600,
      db: { state: "up", migration_head: "0023", migrations_ok: true, latency_ms: 3 },
      counters: { organizations: 2, users: 5 },
      jobs: { open: 0, by_status: {} },
      process: { pid: 42, threads: 8 },
      host: { load: { "1m": 0.1, "5m": 0.1, "15m": 0.1 }, disk: {} },
    })));
    renderAdmin();
    // The landing view is the overview, not the wall of settings it used to be.
    expect(await screen.findByRole("heading", { name: "نمای کلی", level: 1 })).toBeInTheDocument();
    for (const label of ["سازمان‌ها", "مالی و اشتراک", "پایش عملیات", "هوش مصنوعی", "رویدادها", "وضعیت سامانه"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("serves each workspace from its own URL", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    vi.stubGlobal("fetch", vi.fn(async () => json({ organizations: [] })));
    // A deep link straight into organizations must render organizations — the
    // flat tab strip could not be linked to at all.
    renderAdmin("/admin/organizations");
    expect(await screen.findByRole("heading", { name: "سازمان‌ها", level: 1 })).toBeInTheDocument();
  });

  it("renders adapter-driven settings forms instead of raw JSON textareas", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      // GET /settings/{key} answers {key, value} - the wrapper is the shape the
      // real endpoint has (admin.py:572). The panel used to feed the wrapper
      // itself to the form, which left every control blank.
      if (url.includes("/settings/providers_pricing")) {
        return json({
          key: "providers_pricing",
          value: {
            provider: "openai-compatible",
            base_url: "https://api.example.com/v1",
            api_key: "sk-secret",
            answer_model: "deepseek-v4.1-flash",
            credit_per_1000_tokens_out: 7,
          },
        });
      }
      if (url.includes("/monitoring/ai")) {
        return json({ state: "ok", configured_models: {}, packages: [], usage: null, credit: null });
      }
      return json({});
    }));
    renderAdmin("/admin/ai");
    // Values arrive as typed controls with Persian labels...
    expect(await screen.findByLabelText("درگاه فعال")).toBeInTheDocument();
    expect(await screen.findByLabelText("مدل پاسخ‌دهی")).toHaveValue("deepseek-v4.1-flash");
    expect(screen.getByLabelText("اعتبار به‌ازای هر ۱۰۰۰ توکن خروجی")).toHaveValue(7);
    // ...and no textarea anywhere in the panel.
    expect(document.querySelector("textarea")).toBeNull();
  });
});

describe("Operations workspace", () => {
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
    configured_models: { chat: "deepseek-v4.1-flash" },
    credit: { remaining_irt: 1926851.85, remaining_unit: 0, account_tier: 3, exchange_rate: 228650 },
    usage: { transactions: 939, tokens_total: 120612078, tokens_cached: 93699748, cost_unit: 4.54, cost_irt: 2601.64 },
    usage_by_model: [],
    packages: [{ name: "وایب کُدر روزانه حرفه‌ای", remaining_irt: 1913040.57, days_left: 0.86, models: ["deepseek-v4.1-flash"] }],
    covered_models: ["deepseek-v4.1-flash"],
  };

  const backupPayload = {
    state: "ok",
    files: 7,
    latest: { name: "hiveos-20260913-033001.dump", size_bytes: 82_534, age_hours: 13.4, created_at: "2026-09-13T03:30:01Z" },
  };

  function stub(payloads: { host?: unknown; ai?: unknown; backup?: unknown }) {
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/monitoring/host")
        ? payloads.host
        : url.includes("/monitoring/ai")
          ? payloads.ai
          : (payloads.backup ?? backupPayload);
      return json(body);
    });
    vi.stubGlobal("fetch", fn);
    return fn;
  }

  it("shows server resources as Persian gauges", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({ host: hostPayload, ai: aiPayload });
    renderAdmin("/admin/operations");
    expect(await screen.findByTestId("gauge-value-پردازنده")).toHaveTextContent("۲۳٫۵٪");
    expect(screen.getByTestId("gauge-value-حافظه")).toHaveTextContent("۳۳٫۳٪");
    expect(screen.getByTestId("gauge-value-فضای دیسک — /")).toHaveTextContent("۱۵٫۲٪");
    // The gauge is a real progressbar, not a positioned div.
    expect(screen.getByRole("progressbar", { name: "پردازنده" })).toHaveAttribute("aria-valuenow", "24");
  });

  it("shows the AI balance in Toman and flags an expiring package", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({ host: hostPayload, ai: aiPayload });
    renderAdmin("/admin/ai");
    expect(await screen.findByTestId("ai-balance")).toHaveTextContent("۱٬۹۲۶٬۸۵۲");
    // days_left 0.86 is inside the three-day window, so the PO gets a warning
    // rather than having to notice a small number on a card.
    expect(screen.getByTestId("ai-credit-warning")).toBeInTheDocument();
    expect(screen.getByText(/به پایان می‌رسد/)).toBeInTheDocument();
  });

  it("explains a provider with no account API instead of showing an error", async () => {
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({ host: hostPayload, ai: { state: "unsupported", reason: "NO_ACCOUNT_API", credit: null, usage: null, usage_by_model: [], packages: [], covered_models: [] } });
    renderAdmin("/admin/ai");
    expect(await screen.findByText(/امکان گزارش اعتبار را ارائه نمی‌دهد/)).toBeInTheDocument();
  });

  it("warns when the nightly backup has gone stale", async () => {
    // A cron that silently stopped is the failure the page exists to catch:
    // otherwise the PO only learns there was no backup during a restore.
    sessionStorage.setItem("hiveos.admin", "adm-token");
    stub({
      host: hostPayload,
      ai: aiPayload,
      backup: {
        state: "stale",
        files: 1,
        latest: { name: "hiveos-20260910-033001.dump", size_bytes: 80_000, age_hours: 74.2, created_at: "2026-09-10T03:30:01Z" },
      },
    });
    renderAdmin("/admin/operations");
    const card = await screen.findByTestId("backup-card");
    expect(card).toHaveTextContent("قدیمی‌تر از موعد");
    // 'stale' is its own state: "degraded" would hide the one failure this card
    // exists to surface — a cron that silently stopped.
    expect(within(card).getByTestId("backup-state")).toHaveTextContent("قدیمی‌تر از موعد");
    // The dump name is an internal identifier, not something to hide.
    expect(card).toHaveTextContent("hiveos-20260910-033001.dump");
  });
});
