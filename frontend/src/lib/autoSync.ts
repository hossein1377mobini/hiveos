// Automatic background sync for the client folder (US-007, PO request).
//
// The folder is on the owner's own machine, so this loop runs HERE, in the
// desktop client. It never decides the cadence itself: it asks the server
// (GET /client-folder/sync-plan) and obeys, so the interval stays a single
// server-side setting (admin panel, US-1606) that reaches every installed
// client without shipping a new build.
import { api } from "../api/client";
import { syncClientFolder } from "./folderSync";

const POLL_MS = 5 * 60 * 1000; // ask the server every five minutes
const CONFIG_KEY = "hiveos.clientFolder";

export interface SyncPlan {
  due: boolean;
  reason: string;
  interval_minutes: number | null;
  last_scanned_at: string | null;
  next_due_at: number | null;
  pending_uploads: number;
  // The server's own `upload_max_file_mb`. Declared here for a while but never
  // read (P1-6): the upload loop POSTed files the server had already refused on
  // size, spending the request budget on guaranteed failures.
  max_file_mb: number;
}

/** The folder this client is responsible for, remembered across restarts. */
export function rememberedFolder(): string | null {
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { folder?: string };
    return parsed.folder || null;
  } catch {
    return null;
  }
}

export function rememberFolder(folder: string): void {
  localStorage.setItem(CONFIG_KEY, JSON.stringify({ folder }));
}

let timer: number | null = null;
let running = false;

async function tick(): Promise<void> {
  if (running) return; // a slow sync must not stack up
  const folder = rememberedFolder();
  if (!folder || !window.hiveosDesktop) return;
  running = true;
  try {
    const plan = await api<SyncPlan>("GET", "/knowledge-sources/client-folder/sync-plan");
    // P1-6: hand the advertised limit to the sync so oversize files are
    // rejected locally instead of being uploaded and refused.
    if (plan.due) await syncClientFolder(folder, undefined, plan.max_file_mb);
  } catch {
    // Offline, logged out or the folder moved: the next tick tries again.
  } finally {
    running = false;
  }
}

/**
 * Start the polling loop. Safe to call repeatedly - only one timer is kept.
 * Returns a stop function (used by tests and by logout).
 */
export function startAutoSync(): () => void {
  stopAutoSync();
  void tick();
  timer = window.setInterval(() => void tick(), POLL_MS);
  return stopAutoSync;
}

export function stopAutoSync(): void {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}
