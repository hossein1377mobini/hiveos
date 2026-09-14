import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Subscription from "./Subscription";
import { renderWithRouter } from "../test/render";

/**
 * Subscription page — behaviour that matters to the PO.
 *
 * The page had no test at all. The two things worth pinning are the ones that
 * were wrong before: the expired state must be unmistakable, and the remaining
 * days must not change between two renders of the same response (the page used
 * to call Date.now() during render).
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify({ success: true, data }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stub(subscription: unknown) {
  const fn = vi.fn(async () => json({ subscription }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("Subscription", () => {
  it("shows the active plan and its expiry", async () => {
    stub({
      plan: "annual",
      expired: false,
      expires_at: "2027-06-01T00:00:00Z",
      days_left: 200,
    });
    renderWithRouter(<Subscription />, { route: "/subscription" });
    expect(await screen.findByTestId("plan")).toHaveTextContent("فعال");
    expect(await screen.findByTestId("plan")).toHaveTextContent("یک‌ساله");
    expect(screen.getByTestId("expiry")).toHaveTextContent("پایان دوره");
  });

  it("makes the expired state explicit instead of only changing a word", async () => {
    stub({
      plan: "monthly",
      expired: true,
      expires_at: "2026-08-01T00:00:00Z",
      days_left: 0,
    });
    renderWithRouter(<Subscription />, { route: "/subscription" });
    // A banner, not just a different plan label: the operator must be able to
    // tell at a glance why the brain stopped answering.
    expect(await screen.findByTestId("sub-expired-banner")).toBeInTheDocument();
    expect(screen.getByTestId("plan")).toHaveTextContent("منقضی شده");
  });

  it("keeps the remaining-days figure stable across re-renders", async () => {
    // Date.now() during render made this number drift between renders and
    // between the two StrictMode passes of the same data.
    stub({
      plan: "monthly",
      expired: false,
      expires_at: new Date(Date.now() + 10 * 86_400_000).toISOString(),
      days_left: 10,
    });
    const { rerender } = renderWithRouter(<Subscription />, { route: "/subscription" });
    const first = (await screen.findByTestId("expiry")).textContent;
    rerender(<Subscription />);
    await waitFor(() => expect(screen.getByTestId("expiry").textContent).toBe(first));
  });

  it("offers a retry when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ success: false, error: { code: "X", message: "boom" } }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    renderWithRouter(<Subscription />, { route: "/subscription" });
    expect(await screen.findByTestId("subscription-retry")).toBeInTheDocument();
  });
});
