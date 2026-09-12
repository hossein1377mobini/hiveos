import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    expect(await screen.findByTestId("balance")).toHaveTextContent("۵۰");
    expect(screen.getByText("مصرف گفتگو")).toBeInTheDocument();
  });

  it("disables the submit button while a charge request is in flight", async () => {
    const fn = mockApi({
      "GET /wallet": {
        balance: 50,
        welcome_credit: 50,
        blocked: false,
        pending_request: null,
        transactions: [],
      },
    });
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    render(<Wallet />);
    await screen.findByTestId("balance");
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
    render(<Wallet />);
    expect(await screen.findByTestId("zero-credit-banner")).toBeInTheDocument();
    expect(screen.getByTestId("pending")).toHaveTextContent("۲۰۰");
  });
});
