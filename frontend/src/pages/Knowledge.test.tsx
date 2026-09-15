import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Knowledge from "./Knowledge";

/**
 * A route table plus the call log. Keys are "METHOD /path"; a value may be a
 * function when the test needs the payload to change between reloads (that is
 * how "adding a second folder" is modelled without a real server).
 */
function mockApi(routes: Record<string, unknown>, log: string[] = []) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split("?")[0].replace("/api/v1", "");
    const key = (init?.method ?? "GET") + " " + url;
    log.push(key);
    const route = routes[key];
    const value = typeof route === "function" ? (route as () => unknown)() : route;
    if (value === undefined) throw new Error("unexpected call: " + key);
    return new Response(JSON.stringify({ success: true, data: value, message: null }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const SERVER_FOLDER = {
  id: "s1",
  path: "C:/server-docs",
  source_type: "local_folder",
  status: "active",
  discovered_files: 12,
  last_scanned_at: "2026-09-14T09:00:00Z",
};

const CLIENT_FOLDER = {
  id: "s2",
  path: "C:/Users/me/Docs",
  source_type: "client_folder",
  status: "active",
  discovered_files: 3,
  last_scanned_at: null,
};

const PLAN = { max_file_mb: 25 };

function fileNamed(name: string, size: number): File {
  // A real File of that many bytes would allocate; jsdom derives `size` from the
  // parts, so it is overridden instead.
  const file = new File([""], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

afterEach(() => vi.unstubAllGlobals());

describe("Knowledge page (RG-04/05 UI)", () => {
  it("lists assets with Persian status badges and the upload dialog", async () => {
    mockApi({
      "GET /knowledge-assets": {
        assets: [
          { id: "a1", name: "pricing.pdf", status: "ready", size_bytes: 10, extension: ".pdf", origin: "upload" },
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
      "GET /knowledge-sources": [SERVER_FOLDER],
      "GET /knowledge-sources/client-folder/sync-plan": PLAN,
    });
    render(<Knowledge />);
    expect(await screen.findByText("pricing.pdf")).toBeInTheDocument();
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
    // Upload button lives inside the «افزودن سند» dialog (mockup pattern).
    fireEvent.click(screen.getByText("افزودن سند"));
    expect(await screen.findByTestId("upload")).toBeInTheDocument();
  });

  it("renders every registered folder, each with its own state", async () => {
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER, CLIENT_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
      },
      log,
    );
    render(<Knowledge />);
    await screen.findByTestId("folder-s1");

    // The second folder is rendered next to the first, not instead of it.
    expect(screen.getByTestId("folder-s2")).toBeInTheDocument();
    expect(screen.getByTestId("folder-files-s1")).toHaveTextContent("۱۲");
    expect(screen.getByTestId("folder-files-s2")).toHaveTextContent("۳");
    expect(screen.getByTestId("folder-kind-s2")).toHaveTextContent("روی رایانهٔ شما");
    expect(screen.getByTestId("folder-kind-s1")).toHaveTextContent("روی سرور");
    // A folder that has never completed a scan says so rather than dating itself.
    expect(screen.getByTestId("folder-scanned-s2")).toHaveTextContent("هنوز انجام نشده");
    // Per-folder controls exist for both, labelled by what they actually do.
    expect(screen.getByTestId("folder-scan-s1")).toHaveTextContent("پویش اکنون");
    expect(screen.getByTestId("folder-scan-s2")).toHaveTextContent("همگام‌سازی اکنون");
    expect(screen.getByTestId("folder-toggle-s1")).toBeInTheDocument();
    expect(screen.getByTestId("folder-remove-s1")).toBeInTheDocument();
    // The PO's exact complaint: adding a folder is always reachable.
    expect(screen.getByTestId("add-folder")).toBeInTheDocument();
  });

  it("scans a local_folder via /scan and never calls /scan for a client_folder (P0-3)", async () => {
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER, CLIENT_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        "POST /knowledge-sources/s1/scan": { file_state: 12 },
      },
      log,
    );
    render(<Knowledge />);
    await screen.findByTestId("folder-s1");

    // A server-side folder keeps the manual scan call.
    fireEvent.click(screen.getByTestId("folder-scan-s1"));
    await waitFor(() =>
      expect(log).toContain("POST /knowledge-sources/s1/scan"),
    );

    // The client folder's own action is NOT the /scan endpoint: the server can
    // never read a folder on the user's machine, so that call is a guaranteed
    // 400 INGESTION_PATH_NOT_READABLE. In a plain browser the folder does not
    // exist either, so the control is offered disabled rather than failing.
    expect(log).not.toContain("POST /knowledge-sources/s2/scan");
    const clientAction = screen.getByTestId("folder-scan-s2");
    expect(clientAction).toBeDisabled();
    fireEvent.click(clientAction);
    expect(log).not.toContain("POST /knowledge-sources/s2/scan");
    // It explains where the sync happens instead of pretending to scan.
    expect(screen.getByText(/همگام‌سازی از برنامهٔ HiveOS روی رایانهٔ شما/)).toBeInTheDocument();
  });

  it("adds another folder without replacing the ones already registered", async () => {
    const log: string[] = [];
    let folders: unknown = [SERVER_FOLDER];
    const fn = mockApi(
      {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": () => folders,
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        "POST /knowledge-sources": { id: "s9" },
      },
      log,
    );
    render(<Knowledge />);
    await screen.findByTestId("folder-s1");

    fireEvent.click(screen.getByTestId("add-folder"));
    fireEvent.change(await screen.findByTestId("new-folder-path"), {
      target: { value: "D:/Work/Docs" },
    });
    // The server now reports two folders; the page must show both.
    folders = [SERVER_FOLDER, { ...SERVER_FOLDER, id: "s9", path: "D:/Work/Docs", discovered_files: 0, last_scanned_at: null }];
    fireEvent.click(screen.getByTestId("add-folder-submit"));

    await waitFor(() => expect(screen.getByTestId("folder-s9")).toBeInTheDocument());
    expect(screen.getByTestId("folder-s1")).toBeInTheDocument();

    const post = fn.mock.calls.find((call) => call[1]?.method === "POST");
    expect(String(post?.[0])).toContain("/knowledge-sources");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ path: "D:/Work/Docs" });
  });

  it("rejects oversize files in the picker, before any upload (P1-5)", async () => {
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER],
        // The cap is the server's own setting, not a hardcoded number.
        "GET /knowledge-sources/client-folder/sync-plan": { max_file_mb: 25 },
      },
      log,
    );
    const { container } = render(<Knowledge />);
    await screen.findByTestId("folder-s1");

    // With no documents yet the empty state offers the same action, so the
    // page header's button is picked explicitly.
    fireEvent.click(screen.getAllByText("افزودن سند")[0]);
    // The limit is visible up front, in Persian digits.
    expect(await screen.findByTestId("dropzone-limit")).toHaveTextContent("۲۵ مگابایت");

    const input = container.ownerDocument.querySelector('input[type="file"]') as HTMLInputElement;
    const big = fileNamed("big.pdf", 26 * 1024 * 1024);
    fireEvent.change(input, { target: { files: [big] } });

    // Refused with a Persian reason naming the file, and never queued.
    expect(await screen.findByTestId("knowledge-error")).toHaveTextContent("بزرگ‌تر");
    expect(screen.getByTestId("knowledge-error")).toHaveTextContent("big.pdf");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(log.some((key) => key.includes("/knowledge-assets/upload"))).toBe(false);

    // A file inside the cap still goes through.
    fireEvent.change(input, { target: { files: [fileNamed("small.pdf", 1024)] } });
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
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
      "GET /knowledge-sources": [SERVER_FOLDER],
      "GET /knowledge-sources/client-folder/sync-plan": PLAN,
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

  it("accepts a single-object /knowledge-sources payload too (older deployment)", async () => {
    // The multi-folder contract is a list, but a deployment that still answers
    // one object must not lose its folder card.
    mockApi({
      "GET /knowledge-assets": { assets: [] },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge-sources": { id: "legacy", path: "C:/docs", status: "active", file_state: 7 },
      "GET /knowledge-sources/client-folder/sync-plan": PLAN,
    });
    render(<Knowledge />);
    expect(await screen.findByTestId("folder-legacy")).toBeInTheDocument();
    expect(screen.getByTestId("folder-files-legacy")).toHaveTextContent("۷");
  });

  it("shows the empty state", async () => {
    mockApi({
      "GET /knowledge-assets": { assets: [] },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge-sources": {},
      "GET /knowledge-sources/client-folder/sync-plan": PLAN,
    });
    render(<Knowledge />);
    expect(await screen.findByText("هنوز سندی نیست.")).toBeInTheDocument();
    // "No folder yet" is its own state with the same primary action, so the
    // first folder is as easy to add as the second one.
    expect(screen.getByTestId("folders-empty")).toBeInTheDocument();
  });
});
