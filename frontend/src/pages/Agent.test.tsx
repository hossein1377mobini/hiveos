import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Agent from "./Agent";

/**
 * «ایجنت من» after the PO moved agent behaviour to the organization.
 *
 * These assert the negative that matters: the page must not offer an editor
 * for something the server now refuses. PATCH /agent takes display_name only
 * (extra="forbid") and PATCH /agent/tools answers 403
 * AGENT_SETTINGS_MANAGED_BY_ORGANIZATION, so a persona textarea or a tool
 * checkbox here would look like it saved and then 400/403.
 */

function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = method + " " + url.replace("/api/v1", "");
    const value = routes[key];
    if (value === undefined) throw new Error("unexpected call: " + key);
    return new Response(JSON.stringify({ success: true, data: value, message: null }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const AGENT = {
  id: "a1",
  display_name: "دستیار من",
  persona: "کوتاه و رسمی پاسخ بده.",
  status: "active",
  version: 2,
  allowed_tools: ["build_chart"],
  memory: { total: 1, by_kind: { preference: { count: 1, avg_weight: 1 } } },
};

const MEMORY = {
  memories: [
    {
      id: "m1",
      kind: "preference",
      content: "خروجی را همیشه فارسی بنویس.",
      weight: 1,
      hits: 3,
      misses: 0,
      active: true,
      created_at: "2026-09-14T00:00:00Z",
    },
  ],
};

function tools(unrestricted: boolean) {
  return {
    tools: [
      { name: "build_chart", description: "ساخت نمودار از داده", enabled: true, writes: true },
      { name: "build_report", description: "ساخت گزارش", enabled: !unrestricted, writes: true },
    ],
    allowlist: unrestricted ? [] : ["build_chart"],
    unrestricted,
    managed_by: "organization",
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("Agent page — organization-owned settings", () => {
  it("offers no persona editor and explains who owns the tone", async () => {
    mockApi({
      "GET /agent": AGENT,
      "GET /agent/memory": MEMORY,
      "GET /agent/tools": tools(false),
    });
    render(<Agent />);

    await screen.findByDisplayValue("دستیار من");
    // The persona text is still returned, but it must not be editable here.
    expect(screen.queryByDisplayValue("کوتاه و رسمی پاسخ بده.")).toBeNull();
    // The explanation replaces the control.
    expect(screen.getByText(/لحن و شخصیت دستیار برای همهٔ کاربران سازمان/)).toBeInTheDocument();
    // And it says the persona cannot override the grounding rules.
    expect(screen.getByText(/جای آن‌ها را نمی‌گیرد/)).toBeInTheDocument();
  });

  it("shows the tool allowlist as read-only organization policy", async () => {
    mockApi({
      "GET /agent": AGENT,
      "GET /agent/memory": MEMORY,
      "GET /agent/tools": tools(false),
    });
    const { container } = render(<Agent />);

    await screen.findByText(/مدیر سازمان فقط بخشی از ابزارها/);
    expect(container.querySelectorAll('input[type="checkbox"]').length).toBe(0);
    expect(screen.queryByRole("button", { name: "ذخیرهٔ ابزارها" })).toBeNull();
  });

  it("reads an empty allowlist as every tool, not as an empty toolbox", async () => {
    mockApi({
      "GET /agent": AGENT,
      "GET /agent/memory": MEMORY,
      "GET /agent/tools": tools(true),
    });
    render(<Agent />);

    expect(await screen.findByText(/همهٔ ابزارهای موجود را .* فعال کرده است/)).toBeInTheDocument();
  });

  it("still saves the display name through PATCH /agent with that one key", async () => {
    const fetchMock = mockApi({
      "GET /agent": AGENT,
      "GET /agent/memory": MEMORY,
      "GET /agent/tools": tools(false),
      "PATCH /agent": { ...AGENT, display_name: "دستیار فروش", version: 3 },
    });
    render(<Agent />);

    const input = await screen.findByPlaceholderText("مثلاً دستیار فروش من");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(input, { target: { value: "دستیار فروش" } });
    fireEvent.click(screen.getByRole("button", { name: "ذخیره" }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (call) => (call[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      // Exactly display_name: sending persona would 400 VALIDATION_ERROR now.
      expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({
        display_name: "دستیار فروش",
      });
    });
  });

  it("keeps the memory list working", async () => {
    mockApi({
      "GET /agent": AGENT,
      "GET /agent/memory": MEMORY,
      "GET /agent/tools": tools(false),
    });
    render(<Agent />);

    expect(await screen.findByText("خروجی را همیشه فارسی بنویس.")).toBeInTheDocument();
    expect(screen.getByLabelText("حذف این خاطره")).toBeInTheDocument();
  });
});
