import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithRouter } from "../test/render";
import Subscription from "./Subscription";
import Wallet from "./Wallet";
import WalletPage from "./WalletPage";

/**
 * The merged page answers on both addresses.
 *
 * PO request: «صفحه اشتراک و کیف پول رو هم با هم ادغام کن». The merge would be
 * incomplete if a bookmark to /subscription stopped resolving, so both page
 * modules resolve to the one merged implementation - Wallet by re-export,
 * Subscription through a thin wrapper that keeps the prop App.tsx still passes.
 * This pins that: if either module is ever given its own body again, the merge
 * has silently come undone and the operator sees two different pages.
 *
 * App.tsx owns the routes; this file only asserts the module graph, so it can
 * be deleted along with the alias modules once App.tsx redirects /subscription.
 */
afterEach(() => vi.unstubAllGlobals());

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const data = url.includes("/auth/onboarding-status")
        ? { subscription: { plan: "monthly", expired: false, expires_at: null } }
        : { balance: 50, welcome_credit: 50, blocked: false, pending_request: null, transactions: [] };
      return new Response(JSON.stringify({ success: true, data, message: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

describe("merged page aliases", () => {
  it("re-exports the merged component from the wallet module", () => {
    expect(Wallet).toBe(WalletPage);
  });

  it("renders the merged page at the subscription address too", async () => {
    stub();
    renderWithRouter(<Subscription />, { route: "/subscription" });
    // The same single page: one h1, and both merged sections present.
    expect(await screen.findByRole("heading", { level: 1, name: "کیف پول و اشتراک" })).toBeInTheDocument();
    expect(await screen.findByTestId("balance")).toBeInTheDocument();
    expect(await screen.findByTestId("plan")).toBeInTheDocument();
  });
});
