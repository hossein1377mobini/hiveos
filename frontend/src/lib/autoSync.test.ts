import { afterEach, describe, expect, it, vi } from "vitest";
import { rememberedFolder, rememberFolder, startAutoSync, stopAutoSync } from "./autoSync";

// PO request: the client keeps the folder in sync on its own. The cadence is a
// SERVER setting, so the loop must ask the server rather than hardcode one.
function stubBridge(scanFolder = vi.fn()) {
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

function stubFetch(plan: unknown) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    return new Response(JSON.stringify({ success: true, data: plan, message: null }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
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
    const fetchMock = stubFetch({ due: true, reason: "FIRST_SYNC" });
    startAutoSync();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("asks the server and stays put when the server says not due", async () => {
    rememberFolder("C:/Docs");
    stubBridge();
    const fetchMock = stubFetch({ due: false, reason: "NOT_DUE", interval_minutes: 30 });
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
});
