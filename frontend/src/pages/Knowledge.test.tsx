import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Knowledge from "./Knowledge";

function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input).split("?")[0];
    const key = "GET " + url.replace("/api/v1", "");
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

afterEach(() => vi.unstubAllGlobals());

describe("Knowledge page (RG-04/05 UI)", () => {
  it("lists assets with Persian status badges and the upload dialog", async () => {
    mockApi({
      "GET /knowledge/assets": {
        assets: [
          { id: "a1", name: "پricing.pdf", status: "ready", size_bytes: 10, extension: ".pdf", origin: "upload" },
          { id: "a2", name: "old.docx", status: "queued", size_bytes: 10, extension: ".docx", origin: "folder_scan" },
          { id: "a3", name: "bad.csv", status: "failed", size_bytes: 10, extension: ".csv", origin: "upload" },
        ],
      },
      "GET /processing/jobs": {
        jobs: [{ id: "j1", asset_id: "a3", status: "FAILED", stage: null, error_code: "PARSE_FAILED" }],
      },
      "GET /knowledge": { id: "s1", path: "C:/docs", status: "active" },
    });
    render(<Knowledge />);
    expect(await screen.findByText("پricing.pdf")).toBeInTheDocument();
    expect(screen.getByTestId("asset-status-ready")).toHaveTextContent("تکمیل شد");
    expect(screen.getByTestId("asset-status-queued")).toHaveTextContent("در صف");
    expect(screen.getByTestId("asset-status-failed")).toHaveTextContent("ناموفق");
    expect(screen.getByText("PARSE_FAILED")).toBeInTheDocument();
    expect(screen.getByTestId("upload")).toBeInTheDocument();
    expect(screen.getByText("پویش اکنون")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mockApi({
      "GET /knowledge/assets": { assets: [] },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge": {},
    });
    render(<Knowledge />);
    expect(await screen.findByText("هنوز سندی نیست.")).toBeInTheDocument();
  });
});
