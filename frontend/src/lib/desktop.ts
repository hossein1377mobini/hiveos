// Bridge to the HiveOS Windows client (US-007, ADR-023).
//
// The desktop shell injects window.hiveosDesktop (see hiveos-desktop/src/
// preload.js). In a plain browser it is absent, so every call site must have a
// browser fallback - the web build is still used for phones/admin.
export interface DesktopFolderEntry {
  rel_path: string;
  size_bytes: number;
  mtime_ms: number;
  fingerprint: string;
}

export interface DesktopScanResult {
  folder: string;
  name: string;
  entries: DesktopFolderEntry[];
  skipped: { rel_path: string; code: string; limit_mb?: number }[];
  truncated: boolean;
  max_files: number;
  error?: string;
}

interface DesktopBridge {
  isDesktop: boolean;
  platform: string;
  pickFolder(): Promise<{ canceled: boolean; path?: string }>;
  scanFolder(folder: string): Promise<DesktopScanResult>;
  readFile(folder: string, relPath: string): Promise<{ data?: Uint8Array; error?: string }>;
  saveConfig(config: Record<string, unknown>): Promise<{ ok: boolean }>;
  loadConfig(): Promise<Record<string, unknown>>;
}

declare global {
  interface Window {
    hiveosDesktop?: DesktopBridge;
  }
}

export function desktopBridge(): DesktopBridge | null {
  return typeof window !== "undefined" && window.hiveosDesktop ? window.hiveosDesktop : null;
}

export function isDesktop(): boolean {
  return desktopBridge() !== null;
}

/** Open the native folder picker. Browser fallback returns null (no picker). */
export async function pickFolder(): Promise<string | null> {
  const bridge = desktopBridge();
  if (!bridge) return null;
  const result = await bridge.pickFolder();
  if (!result || result.canceled || !result.path) return null;
  return result.path;
}
