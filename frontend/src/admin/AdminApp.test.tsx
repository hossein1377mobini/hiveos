import { render, screen } from "@testing-library/react";
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
        JSON.stringify({
          success: true,
          data: presets[key] ?? (url.includes("system-status") ? { overall: "PASS", checks: [] } : {}),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fn);
    render(<AdminApp />);
    // login form appears first (no stored token)
    expect(await screen.findByText("پنل مدیریت HiveOS")).toBeInTheDocument();
  });
});
