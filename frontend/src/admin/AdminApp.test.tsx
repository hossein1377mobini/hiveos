import { fireEvent, render, screen } from "@testing-library/react";
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
