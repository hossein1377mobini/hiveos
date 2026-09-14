import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Usage from "./Usage";

afterEach(() => vi.unstubAllGlobals());

// The PO's top-up model is manual: a user files a request and the System Admin
// approves it. That only works if the user can see what they hold, what they
// spent it on, and whether a request is already waiting - so each of those is
// asserted here rather than left to a screenshot.

const state = {
  balance: 4200,
  welcome_credit: 500,
  blocked: false,
  pending_request: { id: "r1", amount: 500, created_at: "2026-09-13T10:00:00Z" },
  transactions: [
    { id: "t1", kind: "CHARGE", amount: 1000, balance_after: 4200, execution_id: null, created_at: "2026-09-13T09:00:00Z" },
    { id: "t2", kind: "DEDUCTION", amount: -50, balance_after: 3200, execution_id: "e1", created_at: "2026-09-12T09:00:00Z" },
  ],
};

function stub(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ success: status < 400, data: body }), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  ));
}

describe("Usage page", () => {
  it("shows the balance, charges and spends separately", async () => {
    stub(state);
    render(<Usage />);
    expect(await screen.findByTestId("usage-balance")).toHaveTextContent("۴٬۲۰۰");
    expect(screen.getByTestId("usage-charged")).toHaveTextContent("۱٬۰۰۰");
    expect(screen.getByTestId("usage-spent")).toHaveTextContent("۵۰");
  });

  it("tells the user a charge request is already pending", async () => {
    stub(state);
    render(<Usage />);
    expect(await screen.findByTestId("usage-pending")).toHaveTextContent("۵۰۰");
  });

  it("labels transactions in Persian rather than raw enum values", async () => {
    stub(state);
    render(<Usage />);
    expect(await screen.findByText("شارژ")).toBeInTheDocument();
    expect(screen.getByText("مصرف")).toBeInTheDocument();
    expect(screen.queryByText("DEDUCTION")).not.toBeInTheDocument();
  });

  it("offers a retry instead of a dead screen when loading fails", async () => {
    stub(null, 500);
    render(<Usage />);
    expect(await screen.findByTestId("usage-retry")).toBeInTheDocument();
  });

  it("warns when the balance is exhausted", async () => {
    stub({ ...state, balance: 0, blocked: true, pending_request: null });
    render(<Usage />);
    expect(await screen.findByTestId("usage-zero-banner")).toBeInTheDocument();
  });
});
