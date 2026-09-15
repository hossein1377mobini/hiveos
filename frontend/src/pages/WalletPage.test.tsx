import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import WalletPage from "./WalletPage";

/**
 * The merged «کیف پول و اشتراک» page (RG-15/16 + subscription).
 *
 * PO request 2026-09 merged the wallet and subscription screens, so this file
 * is the merged suite: the three wallet behaviours and the four subscription
 * behaviours that used to live in Wallet.test.tsx and Subscription.test.tsx are
 * kept verbatim, plus what only a single page can be wrong about - that both
 * halves load together, and that one failing does not take the other down.
 *
 * The page always calls BOTH endpoints, so the stub supplies both and the
 * arguments are overrides. Leaving one out used to be a silent hole in a
 * page-local mock; here it would be "unexpected call", which is the point.
 */
function mockApi(routes: Record<string, unknown>) {
  const table: Record<string, unknown> = {
    "GET /wallet": {
      balance: 50,
      welcome_credit: 50,
      blocked: false,
      pending_request: null,
      transactions: [],
    },
    "GET /auth/onboarding-status": {
      subscription: { plan: "monthly", expired: false, expires_at: null },
    },
    ...routes,
  };
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split("?")[0];
    const method = (init?.method ?? "GET").toUpperCase();
    const key = method + " " + url.replace("/api/v1", "");
    const value = table[key];
    if (value === undefined) throw new Error("unexpected call: " + key);
    const failure = value as { status?: number; code?: string; message?: string };
    const body = failure.code
      ? { success: false, error: { code: failure.code, message: failure.message ?? "" } }
      : { success: true, data: value, message: null };
    // Only a numeric status is an HTTP status: the wallet payload carries its
    // own "blocked" and "pending_request", and reading a field as a code made
    // every stubbed failure answer 200 with a broken body.
    const httpStatus = typeof failure.status === "number" ? failure.status : 200;
    return new Response(JSON.stringify(body), {
      status: httpStatus,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Wallet + subscription page (RG-15/16)", () => {
  it("shows balance and transactions", async () => {
    mockApi({
      "GET /wallet": {
        balance: 50,
        welcome_credit: 50,
        blocked: false,
        pending_request: null,
        transactions: [
          { id: "t1", kind: "DEDUCTION", amount: 3, balance_after: 47, created_at: "" },
        ],
      },
    });
    render(<WalletPage />);
    expect(await screen.findByTestId("balance")).toHaveTextContent("۵۰");
    expect(screen.getByText("مصرف گفتگو")).toBeInTheDocument();
  });

  it("disables the submit button while a charge request is in flight", async () => {
    const fn = mockApi({});
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    render(<WalletPage />);
    // Both mounts must have settled before the one-shot override is installed,
    // or it could swallow the subscription request instead of the POST.
    await screen.findByTestId("balance");
    await screen.findByTestId("plan");
    fn.mockImplementationOnce(async () => gate); // POST /wallet/charge-request hangs
    const submit = screen.getByRole("button", { name: "ثبت درخواست شارژ" });
    fireEvent.click(submit);
    await waitFor(() => expect(submit).toBeDisabled()); // D7: a second click would double-file
    release(
      new Response(JSON.stringify({ success: true, data: {}, message: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("shows the zero-credit banner when blocked", async () => {
    mockApi({
      "GET /wallet": {
        balance: 0,
        welcome_credit: 50,
        blocked: true,
        pending_request: { id: "r1", amount: 200 },
        transactions: [],
      },
    });
    render(<WalletPage />);
    expect(await screen.findByTestId("zero-credit-banner")).toBeInTheDocument();
    expect(screen.getByTestId("pending")).toHaveTextContent("۲۰۰");
  });

  it("shows the active plan and its expiry", async () => {
    mockApi({
      "GET /auth/onboarding-status": {
        subscription: {
          plan: "annual",
          expired: false,
          expires_at: "2027-06-01T00:00:00Z",
          days_left: 200,
        },
      },
    });
    render(<WalletPage />);
    expect(await screen.findByTestId("plan")).toHaveTextContent("فعال");
    expect(screen.getByTestId("plan")).toHaveTextContent("یک‌ساله");
    expect(screen.getByTestId("expiry")).toHaveTextContent("پایان دوره");
  });

  it("makes the expired state explicit instead of only changing a word", async () => {
    mockApi({
      "GET /auth/onboarding-status": {
        subscription: {
          plan: "monthly",
          expired: true,
          expires_at: "2026-08-01T00:00:00Z",
          days_left: 0,
        },
      },
    });
    render(<WalletPage />);
    // A banner, not just a different plan label: the operator must be able to
    // tell at a glance why the brain stopped answering.
    expect(await screen.findByTestId("sub-expired-banner")).toBeInTheDocument();
    expect(screen.getByTestId("plan")).toHaveTextContent("منقضی شده");
  });

  it("keeps the remaining-days figure stable across re-renders", async () => {
    // Date.now() during render made this number drift between renders and
    // between the two StrictMode passes of the same data.
    mockApi({
      "GET /auth/onboarding-status": {
        subscription: {
          plan: "monthly",
          expired: false,
          expires_at: new Date(Date.now() + 10 * 86_400_000).toISOString(),
          days_left: 10,
        },
      },
    });
    const { rerender } = render(<WalletPage />);
    const first = (await screen.findByTestId("expiry")).textContent;
    rerender(<WalletPage />);
    await waitFor(() => expect(screen.getByTestId("expiry").textContent).toBe(first));
  });

  it("offers a retry when the subscription request fails", async () => {
    mockApi({
      "GET /auth/onboarding-status": { status: 500, code: "X", message: "boom" },
    });
    render(<WalletPage />);
    expect(await screen.findByTestId("subscription-retry")).toBeInTheDocument();
  });

  it("offers a retry when the wallet request fails", async () => {
    mockApi({ "GET /wallet": { status: 500, code: "X", message: "boom" } });
    render(<WalletPage />);
    expect(await screen.findByTestId("wallet-retry")).toBeInTheDocument();
  });

  it("loads the wallet and the subscription together, under one heading", async () => {
    const fn = mockApi({});
    render(<WalletPage />);
    expect(await screen.findByTestId("balance")).toBeInTheDocument();
    expect(await screen.findByTestId("plan")).toBeInTheDocument();
    // The merged page is one page, so it carries one level-one heading and the
    // three sections below it are all level two - a merged screen that kept the
    // two old h1s would fail the axe heading-order rule.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("کیف پول و اشتراک");
    expect(
      screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent),
    ).toEqual(["اعتبار و شارژ", "اشتراک", "تراکنش‌ها"]);
    const urls = fn.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/wallet"))).toBe(true);
    expect(urls.some((u) => u.includes("/auth/onboarding-status"))).toBe(true);
  });

  it("keeps the wallet usable when only the subscription request fails", async () => {
    // The two halves load independently. A merged page that waited for both, or
    // that returned one error screen for either, would hide a perfectly good
    // balance behind a plan lookup that is not the operator's problem.
    mockApi({ "GET /auth/onboarding-status": { status: 500, code: "X", message: "boom" } });
    render(<WalletPage />);
    expect(await screen.findByTestId("subscription-retry")).toBeInTheDocument();
    expect(screen.getByTestId("balance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ثبت درخواست شارژ" })).toBeInTheDocument();
  });
});
