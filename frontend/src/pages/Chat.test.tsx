import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chat from "./Chat";

function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split("?")[0];
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

describe("Chat page (RG-14)", () => {
  it("renders messages and disabled composer when wallet is blocked", async () => {
    mockApi({
      "GET /chat/sessions": {
        sessions: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
      },
      "GET /chat/sessions/s1/messages": {
        messages: [
          { id: "m1", role: "USER", body: { text: "سلام" }, created_at: "" },
          {
            id: "m2",
            role: "ASSISTANT",
            body: {
              text: "پاسخ با منبع",
              citations: [{ title: "دستورالعمل.pdf", locator: "صفحه ۳" }],
            },
            created_at: "",
          },
        ],
      },
      "GET /wallet": { balance: 0, blocked: true },
    });
    render(<Chat />);
    expect(await screen.findByText("سلام")).toBeInTheDocument();
    expect(await screen.findByText("پاسخ با منبع")).toBeInTheDocument();
    expect(screen.getByTestId("zero-credit-banner")).toBeInTheDocument();
    expect(screen.getByLabelText("متن پیام")).toBeDisabled();
    expect(screen.getByText("منابع:")).toBeInTheDocument();
  });
});
