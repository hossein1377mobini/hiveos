import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { clearToken } from "../api/client";

// US-007 (PO decision 2026-09-14) regression: the folder step must offer a real
// picker in the Windows client and must NOT send the owner's own folder path to
// the server-side registration endpoint (which validates it as a path on the
// server and rejected every real client path with INGESTION_PATH_NOT_ABSOLUTE).
function mockApi(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.replace("/api/v1", "")}`;
    const value = routes[key];
    if (value === undefined) throw new Error(`unexpected call: ${key}`);
    const failure = value as { status?: number; code?: string; message?: string };
    const status = failure.status ?? 200;
    const body =
      failure.code
        ? { success: false, error: { code: failure.code, message: failure.message ?? "" } }
        : { success: true, data: value, message: null };
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const READY_STATUS = {
  organization_status: "active",
  workspace_ready: true,
  brain_ready: true,
  knowledge_source: null,
  next_step: "knowledge_source",
};

function installDesktopBridge(overrides: Record<string, unknown> = {}) {
  const calls: string[] = [];
  const bridge = {
    isDesktop: true,
    platform: "win32",
    pickFolder: vi.fn(async () => {
      calls.push("pickFolder");
      return { canceled: false, path: "C:\\Docs" };
    }),
    scanFolder: vi.fn(async (folder: string) => {
      calls.push(`scanFolder:${folder}`);
      return {
        folder,
        name: "Docs",
        entries: [
          { rel_path: "a.pdf", size_bytes: 12, mtime_ms: 1, fingerprint: "f1" },
        ],
        skipped: [],
        truncated: false,
        max_files: 5000,
      };
    }),
    readFile: vi.fn(async () => ({ data: new Uint8Array([1, 2, 3]) })),
    saveConfig: vi.fn(async () => ({ ok: true })),
    loadConfig: vi.fn(async () => ({})),
    ...overrides,
  };
  (window as unknown as { hiveosDesktop?: unknown }).hiveosDesktop = bridge;
  return { bridge, calls };
}

afterEach(() => {
  clearToken();
  vi.unstubAllGlobals();
  delete (window as unknown as { hiveosDesktop?: unknown }).hiveosDesktop;
});

describe("US-007 client folder step", () => {
  it("offers a native picker and registers the picked folder as a client folder", async () => {
    localStorage.setItem("hiveos.session", "tok");
    const { calls } = installDesktopBridge();
    const fetchMock = mockApi({
      "GET /auth/onboarding-status": READY_STATUS,
      "POST /knowledge-sources/client-folder": { id: "src-1", file_state: 0 },
      "POST /knowledge-sources/client-folder/sync": {
        added: 1,
        updated: 0,
        deleted: 0,
        discovered_files: 1,
        skipped: 0,
        rejected: [],
        pending: [{ asset_id: "asset-1", rel_path: "a.pdf" }],
      },
      "POST /knowledge-sources/client-folder/files/asset-1": { asset_id: "asset-1" },
    });
    render(<App />);

    const browse = await screen.findByRole("button", { name: /انتخاب پوشه/ });
    fireEvent.click(browse);

    await waitFor(() => expect(calls).toContain("scanFolder:C:\\Docs"));
    // The picker is what fills the field - the owner never types a path.
    expect(await screen.findByLabelText("مسیر پوشه اسناد")).toHaveValue("C:\\Docs");
    // The server-side endpoint (which rejects client paths) must not be called.
    const paths = fetchMock.mock.calls.map((call) => `${call[1]?.method} ${String(call[0])}`);
    expect(paths.some((p) => p.endsWith("/api/v1/knowledge-sources"))).toBe(false);
    expect(paths).toContain("POST /api/v1/knowledge-sources/client-folder");
  });

  it("shows the Persian reason and a retry button when the sync fails", async () => {
    localStorage.setItem("hiveos.session", "tok");
    installDesktopBridge({
      scanFolder: vi.fn(async () => ({ entries: [], skipped: [], truncated: false, error: "SCAN_FAILED" })),
    });
    mockApi({
      "GET /auth/onboarding-status": READY_STATUS,
      "POST /knowledge-sources/client-folder": { id: "src-1", file_state: 0 },
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /انتخاب پوشه/ }));

    expect(await screen.findByText("ثبت پوشه ناموفق بود.")).toBeInTheDocument();
    expect(
      await screen.findByText("خواندن فهرست فایل‌های پوشه ممکن نشد؛ دوباره تلاش کنید."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /تلاش مجدد/ })).toBeInTheDocument();
  });

  it("keeps the manual server-path field in the browser build (on-prem)", async () => {
    localStorage.setItem("hiveos.session", "tok");
    mockApi({ "GET /auth/onboarding-status": READY_STATUS });
    render(<App />);

    expect(await screen.findByRole("button", { name: "بررسی و ثبت" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /انتخاب پوشه/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("مسیر پوشه اسناد")).not.toHaveAttribute("readonly");
  });
});
