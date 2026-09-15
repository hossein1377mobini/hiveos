import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    // A route may answer with a Promise: that is how "the upload has started but
    // has not resolved yet" is modelled (B1), without a real server.
    const resolved = await value;
    return new Response(JSON.stringify({ success: true, data: resolved, message: null }), {
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

  it("closes the dialog the moment the upload STARTS, and shows the file as uploading (B1)", async () => {
    let assets: Array<Record<string, unknown>> = [];
    // The upload is deliberately left unresolved: the dialog must not wait for it.
    let release!: () => void;
    const started = new Promise<void>((resolve) => {
      release = resolve;
    });
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": () => ({ assets }),
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        "POST /knowledge-assets/upload": () =>
          started.then(() => ({ stored: [{ id: "srv-1", name: "report.pdf" }], rejected: [] })),
      },
      log,
    );
    const { container } = render(<Knowledge />);
    await screen.findByTestId("folder-s1");

    fireEvent.click(screen.getAllByText("افزودن سند")[0]);
    const input = container.ownerDocument.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileNamed("report.pdf", 2048)] } });
    fireEvent.click(await screen.findByTestId("upload"));

    // The request went out, is still open, and the dialog is already gone.
    await waitFor(() => expect(screen.queryByTestId("upload")).not.toBeInTheDocument());
    expect(log).toContain("POST /knowledge-assets/upload");

    // The file is in the list straight away, under a status the API never sends.
    expect(await screen.findByTestId("asset-status-uploading")).toHaveTextContent("در حال بارگذاری");
    expect(screen.getByText("report.pdf")).toBeInTheDocument();

    // Reopening the dialog must not resend the previous selection.
    fireEvent.click(screen.getAllByText("افزودن سند")[0]);
    expect(await screen.findByTestId("upload")).toBeDisabled();
    fireEvent.click(screen.getByText("انصراف"));

    // The server answers with the asset's OWN id: the optimistic row is
    // reconciled away by id, not duplicated.
    assets = [
      { id: "srv-1", name: "report.pdf", status: "queued", size_bytes: 2048, extension: ".pdf", origin: "upload" },
    ];
    release();
    await waitFor(() => expect(screen.queryByTestId("asset-status-uploading")).not.toBeInTheDocument());
    expect(screen.getAllByText("report.pdf")).toHaveLength(1);
    expect(screen.getByTestId("asset-status-queued")).toBeInTheDocument();
  });

  it("keeps a failed upload on screen with a Persian reason and a retry (B1)", async () => {
    let assets: Array<Record<string, unknown>> = [];
    let offline = true;
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": () => ({ assets }),
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        "POST /knowledge-assets/upload": () => {
          if (offline) {
            offline = false;
            // The request itself fails: the file must NOT be dropped.
            throw new Error("network down");
          }
          return { stored: [{ id: "srv-2", name: "broken.pdf" }], rejected: [] };
        },
      },
      log,
    );
    const { container } = render(<Knowledge />);
    await screen.findByTestId("folder-s1");

    fireEvent.click(screen.getAllByText("افزودن سند")[0]);
    const input = container.ownerDocument.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileNamed("broken.pdf", 512)] } });
    fireEvent.click(await screen.findByTestId("upload"));

    const failed = await screen.findByTestId("asset-status-failed");
    expect(failed).toHaveTextContent("ناموفق");
    // The reason is Persian; the thrown English string never reaches the owner.
    expect(failed).toHaveTextContent("ارتباط با سرور برقرار نشد");
    expect(screen.queryByText(/network down/)).not.toBeInTheDocument();

    // Retry re-sends the SAME file and reconciles once the server lists it.
    assets = [
      { id: "srv-2", name: "broken.pdf", status: "queued", size_bytes: 512, extension: ".pdf", origin: "upload" },
    ];
    fireEvent.click(screen.getByTestId("upload-retry-broken.pdf"));
    await waitFor(() => expect(screen.queryByTestId("asset-status-failed")).not.toBeInTheDocument());
    expect(screen.getByTestId("asset-status-queued")).toBeInTheDocument();
    expect(log.filter((key) => key === "POST /knowledge-assets/upload")).toHaveLength(2);
  });

  it("polls while a document can still change and stops once it settles (B2)", async () => {
    vi.useFakeTimers();
    try {
      let status = "queued";
      const log: string[] = [];
      mockApi(
        {
          "GET /knowledge-assets": () => ({
            assets: [{ id: "a1", name: "flow.pdf", status, size_bytes: 10, extension: ".pdf", origin: "upload" }],
          }),
          "GET /processing/jobs": { jobs: [] },
          "GET /knowledge-sources": [SERVER_FOLDER],
          "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        },
        log,
      );
      render(<Knowledge />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByTestId("asset-status-queued")).toBeInTheDocument();

      const beforePoll = log.filter((key) => key === "GET /knowledge-assets").length;
      // One interval later the server reports the finished document.
      status = "ready";
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(screen.getByTestId("asset-status-ready")).toBeInTheDocument();
      expect(log.filter((key) => key === "GET /knowledge-assets").length).toBeGreaterThan(beforePoll);

      // Everything is terminal now: the timer must be gone, not merely quiet.
      const settled = log.filter((key) => key === "GET /knowledge-assets").length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      expect(log.filter((key) => key === "GET /knowledge-assets").length).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers exactly ONE «افزودن پوشه جدید» control, and it is the page-head one (PO request)", async () => {
    // The empty-state card used to repeat the very same button that is always
    // visible in the page head, so a page with no folders showed it twice.
    mockApi({
      "GET /knowledge-assets": { assets: [] },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge-sources": {},
      "GET /knowledge-sources/client-folder/sync-plan": PLAN,
    });
    render(<Knowledge />);
    await screen.findByTestId("folders-empty");

    // The head control survives, testid intact, and it is the only one.
    expect(screen.getByTestId("add-folder")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /افزودن پوشه جدید/ })).toHaveLength(1);

    // The empty-state card keeps its explanation and gained no button back.
    const empty = screen.getByTestId("folders-empty");
    expect(within(empty).getByText("هنوز پوشه‌ای ثبت نشده است.")).toBeInTheDocument();
    expect(empty).toHaveTextContent("پوشهٔ اسناد را ثبت کنید تا پردازش آغاز شود");
    expect(within(empty).queryByRole("button")).not.toBeInTheDocument();

    // And the surviving button still opens the dialog.
    fireEvent.click(screen.getByTestId("add-folder"));
    expect(await screen.findByTestId("new-folder-path")).toBeInTheDocument();
  });

  it("shows a percentage and a bar only when the server sent a progress value", async () => {
    // The backend is adding progress/stage RIGHT NOW, so three shapes arrive in
    // one list: a real number, an explicit null, and an older server that sends
    // neither field at all. Only the first may show a number.
    mockApi({
      "GET /knowledge-assets": {
        assets: [
          {
            id: "p1",
            name: "prep.pdf",
            status: "processing",
            size_bytes: 10,
            extension: ".pdf",
            origin: "upload",
            progress: 50,
            stage: "chunking",
          },
          {
            id: "p2",
            name: "unknown.docx",
            status: "processing",
            size_bytes: 10,
            extension: ".docx",
            origin: "upload",
            progress: null,
            stage: null,
          },
          {
            id: "p3",
            name: "older.txt",
            status: "queued",
            size_bytes: 10,
            extension: ".txt",
            origin: "upload",
          },
          {
            id: "p4",
            name: "done.pdf",
            status: "ready",
            size_bytes: 10,
            extension: ".pdf",
            origin: "upload",
            progress: 100,
            stage: "indexed",
            chunks: 5,
          },
        ],
      },
      "GET /processing/jobs": { jobs: [] },
      "GET /knowledge-sources": [SERVER_FOLDER],
      "GET /knowledge-sources/client-folder/sync-plan": PLAN,
    });
    render(<Knowledge />);
    await screen.findByText("prep.pdf");

    // 50 -> «۵۰٪», with a real progress affordance and the Persian stage name.
    const bar = screen.getByTestId("asset-percent-p1");
    expect(bar).toHaveTextContent("۵۰٪");
    expect(within(bar).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    expect(bar).toHaveTextContent("تقسیم به واحد دانش");
    // A file still being prepared is unmistakable, not a quiet status chip.
    expect(bar).toHaveTextContent("در حال آماده‌سازی");

    // null: no percentage, no bar — the stage label stands in, as before.
    expect(screen.queryByTestId("asset-percent-p2")).not.toBeInTheDocument();
    const nullRow = screen.getByTestId("asset-progress-p2");
    expect(nullRow).not.toHaveTextContent("٪");
    expect(within(nullRow).queryByRole("progressbar")).not.toBeInTheDocument();
    expect(nullRow).toHaveTextContent("در صف پردازش");

    // Absent (older server) behaves exactly like null.
    expect(screen.queryByTestId("asset-percent-p3")).not.toBeInTheDocument();
    expect(screen.getByTestId("asset-progress-p3")).not.toHaveTextContent("٪");

    // Terminal rows hide it: the status badge already says what happened.
    expect(screen.queryByTestId("asset-percent-p4")).not.toBeInTheDocument();
    expect(screen.getByTestId("asset-progress-p4")).toHaveTextContent("۵ واحد دانش");
    expect(screen.getAllByRole("progressbar")).toHaveLength(1);

    // PO report: the page says out loud that some files cannot answer yet.
    expect(screen.getByTestId("knowledge-preparing")).toHaveTextContent("سند هنوز در حال آماده‌سازی است");
  });

  it("never lets the percentage rewind between polls of the same attempt", async () => {
    let progress = 80;
    let scanned = false;
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": () => ({
          assets: [
            {
              id: "m1",
              name: "slow.pdf",
              status: "processing",
              size_bytes: 10,
              extension: ".pdf",
              origin: "upload",
              progress,
              stage: "extracting",
            },
          ],
        }),
        "GET /processing/jobs": { jobs: [] },
        // The folder row moves on the scan, which is how the test knows the
        // reload carrying the LOWER number has landed.
        "GET /knowledge-sources": () =>
          scanned ? [{ ...SERVER_FOLDER, discovered_files: 99 }] : [SERVER_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        "POST /knowledge-sources/s1/scan": () => {
          scanned = true;
          return { discovered_files: 1, files_added: 0, files_updated: 0, files_deleted: 0 };
        },
      },
      log,
    );
    render(<Knowledge />);
    expect(await screen.findByTestId("asset-percent-m1")).toHaveTextContent("۸۰٪");

    // The next sample of the SAME attempt reports less — a dropped poll, a job
    // that restarted a stage. The bar must not jump backwards.
    progress = 40;
    fireEvent.click(screen.getByTestId("folder-scan-s1"));
    await waitFor(() => expect(screen.getByTestId("folder-files-s1")).toHaveTextContent("۹۹"));

    expect(screen.getByTestId("asset-percent-m1")).toHaveTextContent("۸۰٪");
    expect(screen.getByTestId("asset-percent-m1")).not.toHaveTextContent("۴۰٪");
    expect(log.filter((key) => key === "GET /knowledge-assets").length).toBeGreaterThan(1);
  });

  it("reports the REAL counts a manual scan answered with, not a generic success", async () => {
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        // scan_source answers the source payload spread together with the scan
        // result (backend knowledge/service.py).
        "POST /knowledge-sources/s1/scan": {
          id: "s1",
          path: "C:/server-docs",
          status: "active",
          scan_id: "h1",
          scan_type: "manual",
          discovered_files: 12,
          last_scanned_at: "2026-09-15T09:00:00Z",
          files_added: 3,
          files_updated: 2,
          files_deleted: 1,
        },
      },
      log,
    );
    render(<Knowledge />);
    await screen.findByTestId("folder-s1");
    fireEvent.click(screen.getByTestId("folder-scan-s1"));

    const notice = await screen.findByTestId("knowledge-notice");
    expect(notice).toHaveTextContent("۱۲ فایل بررسی شد");
    expect(notice).toHaveTextContent("۳ فایل تازه اضافه شد");
    expect(notice).toHaveTextContent("۲ فایل تغییرکرده به‌روزرسانی شد");
    expect(notice).toHaveTextContent("۱ فایل حذف‌شده علامت خورد");
    // The old, information-free sentence must be gone.
    expect(notice).not.toHaveTextContent("پویش دستی اجرا شد");
  });

  it("says out loud that a scan found no new file", async () => {
    const log: string[] = [];
    mockApi(
      {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
        "POST /knowledge-sources/s1/scan": {
          scan_type: "manual",
          discovered_files: 0,
          files_added: 0,
          files_updated: 0,
          files_deleted: 0,
        },
      },
      log,
    );
    render(<Knowledge />);
    await screen.findByTestId("folder-s1");
    fireEvent.click(screen.getByTestId("folder-scan-s1"));

    const notice = await screen.findByTestId("knowledge-notice");
    expect(notice).toHaveTextContent("پویش انجام شد");
    expect(notice).toHaveTextContent("نداشت");
    expect(notice).not.toHaveTextContent("فایل بررسی شد");
  });

  it("keeps the server's own reason when a scan fails", async () => {
    // A 409 straight from the scan route: the page repeats the SERVER's reason
    // (ApiError.message, which persianError already turned into Persian) and
    // shows no success notice at all.
    const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).split("?")[0].replace("/api/v1", "");
      const key = (init?.method ?? "GET") + " " + url;
      if (key === "POST /knowledge-sources/s1/scan") {
        return new Response(
          JSON.stringify({
            success: false,
            data: null,
            error: { code: "SCAN_ALREADY_RUNNING", message: "A scan is already running for this source." },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        );
      }
      const routes: Record<string, unknown> = {
        "GET /knowledge-assets": { assets: [] },
        "GET /processing/jobs": { jobs: [] },
        "GET /knowledge-sources": [SERVER_FOLDER],
        "GET /knowledge-sources/client-folder/sync-plan": PLAN,
      };
      return new Response(JSON.stringify({ success: true, data: routes[key], message: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fn);
    render(<Knowledge />);
    await screen.findByTestId("folder-s1");
    fireEvent.click(screen.getByTestId("folder-scan-s1"));

    expect(await screen.findByTestId("knowledge-error")).toHaveTextContent(
      "پویش این پوشه از قبل در حال اجراست.",
    );
    expect(screen.queryByTestId("knowledge-notice")).not.toBeInTheDocument();
  });
});
