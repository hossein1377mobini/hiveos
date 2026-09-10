import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// Minimal structural mock of the fetch Response (R5-2): only the members
// HealthBadge consumes, typed against the real Response contract.
function stubFetch(payload: unknown, ok = true) {
  const response = {
    ok,
    json: () => Promise.resolve(payload),
  } satisfies Pick<Response, "ok" | "json">;
  return vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App placeholder shell (T-S0-5)", () => {
  it("renders the app shell sections and reaches /api/health through the proxy", async () => {
    stubFetch({ status: "ok", environment: "dev" });
    render(<App />);

    expect(screen.getByRole("navigation", { name: "ناوبری اصلی" })).toBeInTheDocument();
    expect(screen.getByText("دانش سازمان")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "پایه فرانت‌اند آماده است" }),
    ).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/متصل/)).toBeInTheDocument());
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("shows the unreachable state when the API answers with an error", async () => {
    stubFetch({}, false);
    render(<App />);

    await waitFor(() => expect(screen.getByText("سرویس در دسترس نیست")).toBeInTheDocument());
  });
});
