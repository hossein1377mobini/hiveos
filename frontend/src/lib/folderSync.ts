// Client-folder sync driver (US-007, PO decision 2026-09-14).
//
// Runs inside the HiveOS Windows client: read the folder manifest from the
// owner's machine, hand it to the server, then upload only the bytes the
// server asked for. The server owns all reconciliation decisions (what is new,
// changed or gone); this module just moves bytes and reports progress.
import { api } from "../api/client";

export interface LocalEntry {
  rel_path: string;
  size_bytes: number;
  fingerprint: string;
}

export interface RejectedEntry {
  rel_path: string;
  code: string;
  limit_mb?: number;
}

export interface SyncResult {
  added: number;
  updated: number;
  deleted: number;
  discovered_files: number;
  skipped: number;
  rejected: RejectedEntry[];
  uploaded: number;
  failed: { rel_path: string; code: string }[];
}

/** The code the server itself uses for a file over `upload_max_file_mb`. */
export const OVERSIZE_CODE = "UPLOAD_TOO_LARGE";

export interface LocalScan {
  entries: LocalEntry[];
  skipped: { rel_path: string; code: string }[];
  truncated: boolean;
}

function requireBridge() {
  const bridge = window.hiveosDesktop;
  if (!bridge) throw new Error("CLIENT_BRIDGE_MISSING");
  return bridge;
}

/** Fingerprint + size for every scannable file in the picked folder. */
export async function scanLocalFolder(folder: string): Promise<LocalScan> {
  const result = await requireBridge().scanFolder(folder);
  if (!result || result.error) throw new Error(result?.error || "SCAN_FAILED");
  return {
    entries: result.entries ?? [],
    skipped: (result.skipped ?? []).map((item) => ({
      rel_path: item.rel_path,
      code: item.code,
    })),
    truncated: Boolean(result.truncated),
  };
}

/**
 * Full sync of one folder.
 *
 * onProgress fires per uploaded file so the step can show a real counter
 * instead of an indeterminate spinner on a large folder.
 */
export async function syncClientFolder(
  folder: string,
  onProgress?: (done: number, total: number, name: string) => void,
  maxFileMb?: number,
): Promise<SyncResult> {
  const bridge = requireBridge();
  const manifest = await scanLocalFolder(folder);
  const plan = await api<{
    added: number;
    updated: number;
    deleted: number;
    discovered_files: number;
    skipped: number;
    rejected: RejectedEntry[];
    pending: { asset_id: string; rel_path: string }[];
  }>("POST", "/knowledge-sources/client-folder/sync", {
    entries: manifest.entries.map((entry) => ({
      rel_path: entry.rel_path,
      fingerprint: entry.fingerprint,
      size_bytes: entry.size_bytes,
    })),
  });

  const failed: { rel_path: string; code: string }[] = [];
  const rejected: RejectedEntry[] = [...(plan.rejected ?? [])];

  // P1-6: the plan carries the server's own file-size cap and it used to be
  // thrown away, so an oversized file was read from disk and POSTed only to be
  // refused - burning the 30 req/min knowledge limiter on work that could never
  // succeed. Gate on the size the manifest already reported, before the read.
  //
  // Belt and braces: the server rejects the same file in the manifest, but the
  // sync-plan only reports the limit, not the rejections, so the gate has to
  // exist here too. A file is reported once, never twice.
  const maxBytes = maxFileMb !== undefined ? maxFileMb * 1024 * 1024 : null;
  const bySize = new Map(manifest.entries.map((entry) => [entry.rel_path, entry.size_bytes]));
  const alreadyRejected = new Set(rejected.map((entry) => entry.rel_path));
  const queue: typeof plan.pending = [];
  for (const item of plan.pending) {
    const size = bySize.get(item.rel_path);
    if (maxBytes !== null && size !== undefined && size > maxBytes) {
      if (!alreadyRejected.has(item.rel_path)) {
        rejected.push({ rel_path: item.rel_path, code: OVERSIZE_CODE, limit_mb: maxFileMb });
        alreadyRejected.add(item.rel_path);
      }
      continue;
    }
    queue.push(item);
  }

  const total = queue.length;
  let done = 0;
  for (const item of queue) {
    // A file can be renamed or deleted between the scan and the upload; that
    // is normal and must not abort the run for every other file.
    const file = await bridge.readFile(folder, item.rel_path);
    if (!file || file.error || !file.data) {
      failed.push({ rel_path: item.rel_path, code: file?.error || "READ_FAILED" });
      done += 1;
      onProgress?.(done, total, item.rel_path);
      continue;
    }
    const form = new FormData();
    const name = item.rel_path.split("/").pop() || "file";
    // Uint8Array survives the bridge; a Blob is what fetch wants. Copy into a
    // plain ArrayBuffer because a Uint8Array may be backed by a SharedArrayBuffer,
    // which Blob refuses.
    const bytes = new Uint8Array(file.data);
    form.append(
      "file",
      new Blob([bytes.buffer as ArrayBuffer], { type: "application/octet-stream" }),
      name,
    );
    try {
      await api("POST", "/knowledge-sources/client-folder/files/" + item.asset_id, form);
    } catch (exc) {
      const code =
        exc && typeof exc === "object" && "code" in exc ? String(exc.code) : "UPLOAD_FAILED";
      failed.push({ rel_path: item.rel_path, code });
    }
    done += 1;
    onProgress?.(done, total, item.rel_path);
  }

  return { ...plan, rejected, uploaded: total - failed.length, failed };
}
