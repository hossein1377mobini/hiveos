import { afterEach, describe, expect, it, vi } from "vitest";
import { rememberedFolder, rememberFolder, startAutoSync, stopAutoSync } from "./autoSync";

// PO request: the client keeps the folder in sync on its own. The cadence is a
// SERVER setting, so the loop must ask the server rather than hardcode one.
const SCAN_RESULT = { entries: [] as unknown[], skipped: [], truncated: false, max_files: 1000 };

function stubBridge(scanFolder = vi.fn(async () => SCAN_RESULT)) {
  (window as unknown as { hiveosDesktop?: unknown }).hiveosDesktop = {
    isDesktop: true,
    platform: "win32",
    pickFolder: vi.fn(async () => ({ canceled: true })),
    scanFolder,
    readFile: vi.fn(async () => ({ data: new Uint8Array([1]) })),
    saveConfig: vi.fn(async () => ({ ok: true })),
    loadConfig: vi.fn(async () => ({})),
  };
}

/**
 * Route-aware fetch: "METHOD /path" -> payload. Without it a test cannot tell
 * the sync-plan call from the manifest sync that follows it.
 */
function stubFetch(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split("?")[0].replace("/api/v1", "");
    const key = (init?.method ?? "GET") + " " + url;
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

/** Let the whole startAutoSync -> tick chain of awaits finish. */
async function settle() {
  for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  stopAutoSync();
  vi.unstubAllGlobals();
  localStorage.clear();
  delete (window as unknown as { hiveosDesktop?: unknown }).hiveosDesktop;
});

describe("client folder auto-sync", () => {
  it("does nothing when no folder was ever picked", async () => {
    stubBridge();
    const fetchMock = stubFetch({});
    startAutoSync();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("asks the server and stays put when the server says not due", async () => {
    rememberFolder("C:/Docs");
    stubBridge();
    const fetchMock = stubFetch({
      "GET /knowledge-sources/client-folder/sync-plan": {
        due: false,
        reason: "NOT_DUE",
        interval_minutes: 30,
      },
    });
    startAutoSync();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/client-folder/sync-plan");
  });

  it("remembers the picked folder across restarts", () => {
    expect(rememberedFolder()).toBeNull();
    rememberFolder("D:/Work/Docs");
    expect(rememberedFolder()).toBe("D:/Work/Docs");
    localStorage.setItem("hiveos.clientFolder", "{not json");
    expect(rememberedFolder()).toBeNull();
  });

  it("refuses an oversize file locally instead of uploading it (P1-6)", async () => {
    // The server advertises its own cap on the sync plan. It used to be read and
    // thrown away, so the client uploaded the file anyway and spent one of the
    // 30 requests/minute on a POST the server could only refuse.
    rememberFolder("C:/Docs");
    const oneMb = 1024 * 1024;
    stubBridge(
      vi.fn(async () => ({
        entries: [
          { rel_path: "small.pdf", size_bytes: oneMb, mtime_ms: 1, fingerprint: "a" },
          { rel_path: "huge.pdf", size_bytes: 40 * oneMb, mtime_ms: 1, fingerprint: "b" },
        ],
        skipped: [],
        truncated: false,
        max_files: 1000,
      })),
    );
    const fetchMock = stubFetch({
      "GET /knowledge-sources/client-folder/sync-plan": { due: true, reason: "FIRST_SYNC", max_file_mb: 25 },
      "POST /knowledge-sources/client-folder/sync": {
        added: 2,
        updated: 0,
        deleted: 0,
        discovered_files: 2,
        skipped: 0,
        rejected: [],
        pending: [
          { asset_id: "asset-small", rel_path: "small.pdf" },
          { asset_id: "asset-huge", rel_path: "huge.pdf" },
        ],
      },
      "POST /knowledge-sources/client-folder/files/asset-small": { ok: true },
    });

    startAutoSync();
    await settle();

    const posts = fetchMock.mock.calls.map((call) => String(call[0]));
    // The file that fits is uploaded; the one that cannot succeed never is.
    expect(posts).toContain("/api/v1/knowledge-sources/client-folder/files/asset-small");
    expect(posts).not.toContain("/api/v1/knowledge-sources/client-folder/files/asset-huge");
  });
});
