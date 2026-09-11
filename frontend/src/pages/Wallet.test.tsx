import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Wallet from "./Wallet";

function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = method + " " + url.replace("/api/v1", "");
    const value = routes[key];
    if (value === undefined) throw new Error("unexpected call: " + key);
    const body = { success: true, data: value, message: null };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Wallet page (RG-15/16)", () => {
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
    render(<Wallet />);
    expect(await screen.findByTestId("balance")).toHaveTextContent("50");
    expect(screen.getByText("مصرف")).toBeInTheDocument();
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
    render(<Wallet />);
    expect(await screen.findByTestId("zero-credit-banner")).toBeInTheDocument();
    expect(screen.getByTestId("pending")).toHaveTextContent("200");
  });
});
