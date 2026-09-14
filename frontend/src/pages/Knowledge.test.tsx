import { fireEvent, render, screen } from "@testing-library/react";
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
      "GET /knowledge-assets": {
        assets: [
          { id: "a1", name: "پricing.pdf", status: "ready", size_bytes: 10, extension: ".pdf", origin: "upload" },
          { id: "a2", name: "old.docx", status: "queued", size_bytes: 10, extension: ".docx", origin: "folder_scan" },
          { id: "a3", name: "bad.csv", status: "failed", size_bytes: 10, extension: ".csv", origin: "upload" },
        ],
      },
      "GET /processing/jobs": {
        // The job payload is {id, asset_id, job_type, status, error_detail, ...};
      // error_code and stage do not exist. The worker writes "CODE: detail".
      jobs: [
        {
          id: "j1",
          asset_id: "a3",
          job_type: "create",
          status: "failed",
          error_detail: "EXTRACTION_FAILED: no text could be extracted",
        },
      ],
      },
      "GET /knowledge-sources": { id: "s1", path: "C:/docs", status: "active" },
    });
    render(<Knowledge />);
    expect(await screen.findByText("پricing.pdf")).toBeInTheDocument();
    expect(screen.getByTestId("asset-status-ready")).toHaveTextContent("تکمیل شد");
    expect(screen.getByTestId("asset-status-queued")).toHaveTextContent("در صف");
    expect(screen.getByTestId("asset-status-failed")).toHaveTextContent("ناموفق");
    // PO rule: the failure reason reaches the owner in Persian. The raw code
    // and the developer's English sentence must never appear.
    expect(screen.queryByText(/EXTRACTION_FAILED/)).not.toBeInTheDocument();
    expect(screen.queryByText(/no text could be extracted/)).not.toBeInTheDocument();
    expect(
      screen.getByText("متن این فایل قابل خواندن نبود؛ فایل ممکن است خراب باشد."),
    ).toBeInTheDocument();
    expect(screen.getByText("پویش اکنون")).toBeInTheDocument();
    // Upload button lives inside the «افزودن سند» dialog (mockup pattern).
    fireEvent.click(screen.getByText("افزودن سند"));
    expect(await screen.findByTestId("upload")).toBeInTheDocument();
  });

  it("shows each document's pipeline stage, not just a status (H2)", async () => {
    // "queued" used to be one undifferentiated state, so an operator could not
    // tell a file waiting its turn from one that had been read but not split.
    // The API reports the stage reached; the column renders it.
    mockApi({
      "GET /knowledge-assets": {
        assets: [
          {
            id: "a1",
            name: "done.pdf",
            status: "ready",
            size_bytes: 10,
            extension: ".pdf",
            origin: "upload",
            chunks: 42,
            text_length: 900,
          },
          {
            id: "a2",
            name: "reading.docx",
            status: "queued",
            size_bytes: 10,
            extension: ".docx",
            origin: "upload",
            chunks: 0,
            text_length: 1200,
            pipeline: "text",
          },
          {
            id: "a3",
            name: "waiting.txt",
            status: "queued",
            size_bytes: 10,
            extension: ".txt",
            origin: "upload",
            chunks: 0,
            text_length: 0,
          },
          {
            id: "a4",
            name: "empty.md",
            status: "ready",
            size_bytes: 10,
            extension: ".md",
            origin: "upload",
            chunks: 0,
            text_length: 500,
          },
        ],
      },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge-sources": { id: "s1", path: "C:/docs", status: "active" },
    });
    render(<Knowledge />);
    await screen.findByText("done.pdf");

    // Persian digits, properly formatted, never a raw Latin integer.
    expect(screen.getByTestId("asset-progress-a1")).toHaveTextContent("۴۲ واحد دانش");
    // Read but not yet chunked: must not look like the untouched file below.
    expect(screen.getByTestId("asset-progress-a2")).toHaveTextContent("متن استخراج شد");
    // Thousands separator included: faNum formats counts the Persian way.
    expect(screen.getByTestId("asset-progress-a2")).toHaveTextContent("۱٬۲۰۰ نویسه");
    expect(screen.getByTestId("asset-progress-a3")).toHaveTextContent("در صف پردازش");
    // A ready document with no knowledge units is a real failure mode, and it
    // must not read like success.
    expect(screen.getByTestId("asset-progress-a4")).toHaveTextContent("بدون واحد دانش");
  });

  it("shows the empty state", async () => {
    mockApi({
      "GET /knowledge-assets": { assets: [] },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge-sources": {},
    });
    render(<Knowledge />);
    expect(await screen.findByText("هنوز سندی نیست.")).toBeInTheDocument();
  });
});
