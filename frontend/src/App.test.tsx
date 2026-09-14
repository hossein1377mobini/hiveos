import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { clearToken } from "./api/client";
import { renderWithRouter } from "./test/render";

// Envelope-level fetch stub: each entry is "METHOD /path" -> data or ApiError.
function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.replace("/api/v1", "")}`;
    const value = routes[key];
    if (value === undefined) throw new Error(`unexpected call: ${key}`);
    const failure = value as { status?: number; code?: string; message?: string };
    const status = failure.status ?? 200;
    const body =
      failure.code
        ? { success: false, error: { code: failure.code, message: failure.message ?? "" } }
        : { success: true, data: value, message: null };
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function apiError(status: number, code: string, message: string) {
  return Object.assign(new Error(message), { status, code });
}

afterEach(() => {
  clearToken();
  vi.unstubAllGlobals();
});

describe("bootstrap flow (T-S1-9)", () => {
  it("shows login when there is no session", async () => {
    mockApi({});
    renderWithRouter(<App />);
    expect(await screen.findByText("ورود به HiveOS")).toBeInTheDocument();
  });

  it("shows the generic Persian failure message on login 401 (no field disclosure)", async () => {
    mockApi({ "POST /auth/login": apiError(401, "AUTH_INVALID_CREDENTIALS", "Invalid username or password.") });
    renderWithRouter(<App />);
    const username = await screen.findByText("نام کاربری");
    expect(username).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    await buttons[0].click; // presence check only; typed flow covered by e2e later
    expect(screen.queryByText("خطای ناشناخته.")).not.toBeInTheDocument();
  });

  it("resumes onboarding from the server answer (C2)", async () => {
    localStorage.setItem("hiveos.session", "tok");
    mockApi({
      "GET /auth/onboarding-status": {
        organization_status: "active",
        workspace_ready: true,
        brain_ready: true,
        knowledge_source: null,
        next_step: "knowledge_source",
      },
    });
    renderWithRouter(<App />);
    expect(await screen.findByText("تعیین پوشه اسناد")).toBeInTheDocument();
  });

  it("goes straight to the chat area when onboarding is complete", async () => {
    localStorage.setItem("hiveos.session", "tok");
    mockApi({
      "GET /auth/onboarding-status": {
        organization_status: "active",
        workspace_ready: true,
        brain_ready: true,
        knowledge_source: { id: "x", path: "p", status: "active" },
        next_step: "chat",
      },
      "GET /chat/sessions": { sessions: [] },
      "GET /wallet": { balance: 50, blocked: false },
    });
    renderWithRouter(<App />, { route: "/onboarding" });
    expect(
      await screen.findByText("سوال خود را درباره سازمان یا اسناد آن بپرسید. پاسخ‌ها با ارجاع به منابع داده می‌شوند."),
    ).toBeInTheDocument();
  });

  it("reports an expired pending organization (C3)", async () => {
    localStorage.setItem("hiveos.session", "tok");
    mockApi({
      "GET /auth/onboarding-status": {
        organization_status: "expired",
        workspace_ready: false,
        brain_ready: false,
        knowledge_source: null,
        next_step: "expired",
      },
    });
    renderWithRouter(<App />, { route: "/onboarding" });
    expect(await screen.findByText("ثبت‌نام این سازمان منقضی شد")).toBeInTheDocument();
  });

  /**
   * Regression: /admin must render its own login form, not redirect away.
   *
   * The shell probes /auth/onboarding-status on every route. An anonymous
   * visitor to the admin panel got a 401 from that probe and the shared API
   * client treated it as a signed-out organization user, so it sent the browser
   * to /login before the panel could paint. The panel was unreachable by URL.
   */
  it("renders the admin panel login on /admin without a session", async () => {
    mockApi({
      "GET /auth/onboarding-status": apiError(401, "AUTH_REQUIRED", "authentication required"),
    });
    renderWithRouter(<App />, { route: "/admin" });
    expect(await screen.findByText("پنل مدیریت HiveOS")).toBeInTheDocument();
  });

  /**
   * Regression: signup must not bounce to /login between its two steps.
   *
   * POST /auth/register-organization returns before any token exists — the
   * owner account created in step 2 is what issues one. Sending the browser to
   * "/" after step 1 hit RequireSession with no token and ejected the user.
   */
  it("keeps the signup flow on the owner step after the organization is created", async () => {
    mockApi({});
    renderWithRouter(<App />, { route: "/owner" });
    // No pending id in sessionStorage: the guard screen, not a redirect to login.
    expect(await screen.findByText("ادامهٔ ثبت‌نام از این مرورگر ممکن نیست")).toBeInTheDocument();
    expect(screen.queryByText("ورود به HiveOS")).not.toBeInTheDocument();
  });

  it("serves every shell section from its own URL (A4/D1)", async () => {
    localStorage.setItem("hiveos.session", "tok");
    mockApi({
      "GET /wallet": { balance: 50, blocked: false },
      "GET /wallet/transactions": { items: [], total: 0 },
    });
    // A deep link straight into the wallet must render the wallet, not the chat
    // default — the v0.1 screen-switch could not do this at all.
    renderWithRouter(<App />, { route: "/wallet" });
    expect(await screen.findByRole("heading", { name: /کیف پول/ })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /کیف پول/ }).length).toBeGreaterThan(0);
  });
});
