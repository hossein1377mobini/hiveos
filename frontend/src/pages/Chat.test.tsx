import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chat from "./Chat";

function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split("?")[0];
    const method = (init?.method ?? "GET").toUpperCase();
    const key = method + " " + url.replace("/api/v1", "");
    const value = routes[key];
    if (value === undefined) throw new Error("unexpected call: " + key);
    const failure = value as { status?: number | string; code?: string; message?: string };
    const body = failure.code
      ? { success: false, error: { code: failure.code, message: failure.message ?? "" } }
      : { success: true, data: value, message: null };
    // Only a numeric status is an HTTP status. Payloads carry their own
    // "status" field (an execution's COMPLETED, for example) and reading that
    // as a response code made the runner throw instead of returning a body.
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

describe("Chat page (RG-14)", () => {
  it("reports a failed credit check instead of keeping a stale banner", async () => {
    mockApi({
      "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
      "GET /wallet": { status: 500, code: "SERVER_ERROR", message: "boom" },
    });
    render(<Chat />);
    // PO request: the panel shows an explanatory Persian sentence for the
    // failure - never the server's English "boom", never a stale banner.
    const box = await screen.findByTestId("chat-error");
    expect(box).toHaveTextContent("خطای غیرمنتظره در سرور رخ داد");
    expect(box).not.toHaveTextContent("boom");
    // ...and a first-load failure still offers a way out.
    expect(screen.getByTestId("chat-reload")).toBeInTheDocument();
  });

  it("renders messages and disabled composer when wallet is blocked", async () => {
    mockApi({
      "GET /chat/sessions": {
        items: [{ id: "s1", title: null, status: "ACTIVE", created_at: "" }],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_more: false,
      },
      "GET /chat/sessions/s1/messages": {
        items: [
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

  it("sends the first message for a brand-new organization", async () => {
    // A new organization has no sessions, so activeId is null on the first
    // screen. send() used to return at that point with no message and no
    // error, which made the send button look broken - the PO's report.
    const fetchMock = mockApi({
      "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
      "GET /wallet": { balance: 500, blocked: false },
      "POST /chat/sessions": { id: "new-session" },
      "POST /chat/sessions/new-session/messages": { id: "m1" },
      "POST /executions": { id: "e1" },
      "POST /executions/e1/run": {
        status: "COMPLETED",
        output: { text: "پاسخ سرور" },
        error: null,
      },
      "GET /chat/sessions/new-session/messages": {
        items: [
          { id: "m1", role: "USER", body: { text: "سوال من" }, created_at: "" },
          { id: "m2", role: "ASSISTANT", body: { text: "پاسخ سرور" }, created_at: "" },
        ],
      },
    });
    render(<Chat />);

    const composer = await screen.findByLabelText("متن پیام");
    fireEvent.change(composer, { target: { value: "سوال من" } });
    // Enter is the path the PO uses; a jsdom click on a submit button does not
    // dispatch the form's submit event.
    fireEvent.keyDown(composer, { key: "Enter" });

    // The session is created on demand and the reply is rendered.
    expect(await screen.findByText("پاسخ سرور")).toBeInTheDocument();
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.endsWith("/chat/sessions"))).toBe(true);
    expect(calls.some((u) => u.includes("/executions/e1/run"))).toBe(true);
  });

  it("never leaves the composer silently dead when there is no session", async () => {
    // Whatever else changes, submitting with text must produce a network call:
    // a no-op submit is indistinguishable from a broken button.
    const fetchMock = mockApi({
      "GET /chat/sessions": { items: [], total_count: 0, page: 1, page_size: 20, has_more: false },
      "GET /wallet": { balance: 500, blocked: false },
      "POST /chat/sessions": { status: 500, code: "SERVER_ERROR", message: "boom" },
    });
    render(<Chat />);
    const composer = await screen.findByLabelText("متن پیام");
    fireEvent.change(composer, { target: { value: "سلام" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    const box = await screen.findByTestId("chat-error");
    expect(box).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });
});