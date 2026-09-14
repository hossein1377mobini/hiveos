import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { clearToken } from "./api/client";
import { renderWithRouter } from "./test/render";

/**
 * The shell header names the signed-in person and their organization. This was
 * defect D10/H1: v0.1 rendered a hardcoded «مدیر» and «مدیر سازمان» because
 * /auth/onboarding-status did not return names. The endpoint now sends an
 * identity block, and this test pins the whole chain — response → context →
 * header — because the original bug was exactly a broken chain that typechecked.
 */

const READY = {
  organization_status: "active",
  expired: false,
  workspace_ready: true,
  brain_ready: true,
  knowledge_source: { id: "s1", path: "C:/docs", status: "active" },
  subscription: { plan: "pro", expires_at: "2027-01-01T00:00:00Z", expired: false },
  next_step: "chat",
};

function mockStatus(routeValue: unknown) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input).replace("/api/v1", "");
    if (url.startsWith("/auth/onboarding-status")) {
      const failure = routeValue as { status?: number; code?: string };
      if (failure?.code) {
        return new Response(
          JSON.stringify({ success: false, error: { code: failure.code, message: "" } }),
          { status: failure.status ?? 500, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ success: true, data: routeValue, message: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ success: true, data: {}, message: null }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  clearToken();
  vi.unstubAllGlobals();
});

describe("signed-in identity (D10/H1)", () => {
  it("shows the real user and organization names from the API", async () => {
    localStorage.setItem("hiveos.session", "tok");
    mockStatus({
      ...READY,
      identity: {
        user_name: "manager.ar",
        organization_name: "شرکت داده‌پرداز آریا",
        plan_label: "pro",
      },
    });
    renderWithRouter(<App />, { route: "/chat" });

    await waitFor(() => expect(screen.getByText("manager.ar")).toBeInTheDocument());
    expect(screen.getByText("شرکت داده‌پرداز آریا")).toBeInTheDocument();
    // The hardcoded fallbacks must be gone once real names exist.
    expect(screen.queryByText("مدیر سازمان")).not.toBeInTheDocument();
  });

  it("falls back to the role label when the backend sends no identity", async () => {
    // An older backend must degrade gracefully, not render a blank header.
    localStorage.setItem("hiveos.session", "tok");
    mockStatus(READY);
    renderWithRouter(<App />, { route: "/chat" });

    await waitFor(() => expect(screen.getByText("مدیر")).toBeInTheDocument());
    expect(screen.getByText("مدیر سازمان")).toBeInTheDocument();
  });

  it("still renders the page when the identity lookup fails", async () => {
    // A failed status read must not keep a signed-in user out of the page.
    localStorage.setItem("hiveos.session", "tok");
    mockStatus({ status: 500, code: "INTERNAL_ERROR" });
    renderWithRouter(<App />, { route: "/chat" });

    await waitFor(() => expect(screen.getByText("مدیر")).toBeInTheDocument());
  });
});
