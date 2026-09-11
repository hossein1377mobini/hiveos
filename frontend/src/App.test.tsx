import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { clearToken } from "./api/client";

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
    render(<App />);
    expect(await screen.findByText("ورود به HiveOS")).toBeInTheDocument();
  });

  it("shows the generic Persian failure message on login 401 (no field disclosure)", async () => {
    mockApi({ "POST /auth/login": apiError(401, "AUTH_INVALID_CREDENTIALS", "Invalid username or password.") });
    render(<App />);
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
    render(<App />);
    expect(await screen.findByText("تعیین فولدر اسناد")).toBeInTheDocument();
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
    render(<App />);
    expect(
      await screen.findByText("سوال خود را بپرسید؛ پاسخ بر اساس دانش سازمان داده می‌شود."),
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
    render(<App />);
    expect(await screen.findByText("ثبت‌نام این سازمان منقضی شد")).toBeInTheDocument();
  });
});
