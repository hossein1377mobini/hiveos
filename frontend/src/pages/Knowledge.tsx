import {
  CircleAlert,
  Download,
  FileText,
  FolderOpen,
  FolderPlus,
  MonitorSmartphone,
  Power,
  RefreshCw,
  Search,
  Server,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, ApiError, api, getToken } from "../api/client";
import { persianError } from "../api/errors";
import { DomainStatus } from "../components/ui/domain-status";
import { Banner } from "../components/ui/banner";
import { Button } from "../components/ui/button";
import { LoadingButton } from "../components/ui/button-loading";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { DialogBody } from "../components/ui/dialog-body";
import { Input } from "../components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { RetryNotice } from "../components/ui/retry";
import { cn } from "../lib/utils";
import { pickFolder, isDesktop } from "../lib/desktop";
import { syncClientFolder } from "../lib/folderSync";
import { anyPending, useLive } from "../lib/live";
import { StatusBadge } from "../components/ui/status-badge";
import { faDateTime, faNum, humanSize, norm } from "../utils/format";
import { Surface } from "../components/ui/surface";

// 02-knowledge/01-knowledge-home.html at mockup fidelity: page-head with
// «افزودن پوشه جدید»/«افزودن سند», one card PER registered folder, stat cards,
// status tabs with count chips, live search + format filter, document table with
// format/size/status/actions, table-foot paging, add-document dialog with
// dropzone, empty state.
//
// Multi-folder (PO request 2026-09-14): the page used to manage exactly one
// folder because GET /knowledge-sources answered a single object and the UI had
// no way to register a second one. It now renders the LIST the API returns and
// keeps «افزودن پوشه جدید» visible at all times, so registering another folder
// never replaces the previous ones. Every folder still feeds the SAME
// organization knowledge base; what a person can READ is decided by their
// access level, not by which folder they happened to add - the page says so in
// copy so the model is not surprising.
interface Asset {
  id: string;
  name: string;
  status: string;
  size_bytes: number;
  extension: string;
  origin: string;
  // H2: the pipeline stage, so "queued" is no longer one undifferentiated state.
  asset_type?: string | null;
  pipeline?: string | null;
  text_length?: number;
  chunks?: number;
  // PO request: the server now reports how far THIS file's preparation has got
  // (an integer 0..100) and which stage it reached. Both are optional and both
  // may be null: an older deployment sends neither, and a file whose position
  // the server cannot express sends null. Absence is not zero — it means "not
  // known", and the page must not invent a number for it.
  progress?: number | null;
  stage?: string | null;
}

interface Job {
  id: string;
  asset_id: string | null;
  status: string;
  job_type: string;
  // The job payload has never carried "error_code" or "stage": the worker writes
  // "CODE: developer message" into error_detail (knowledge/worker.py:112) and the
  // API returns exactly that. The page read two fields that do not exist, so a
  // failed document showed no reason at all.
  error_detail: string | null;
}

/**
 * One registered ingestion folder.
 *
 * `source_type` decides whether the SERVER can walk this folder. A
 * `client_folder` lives on the person's own machine (ADR-023), so the server
 * can never read it; only the installed client can sync it.
 */
interface SourceFolder {
  id: string;
  path: string;
  source_type: "local_folder" | "client_folder";
  status: string;
  discovered_files: number | null;
  last_scanned_at: string | null;
  is_org: boolean;
}

// Must stay identical to the server's US-205 table (backend/knowledge/assets.py):
// an extension the picker offers but the server refuses is a broken promise.
const ACCEPTED =
  ".txt,.md,.pdf,.docx,.pptx,.xlsx,.csv,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.webp";

/** Fallback when the server has never told us its cap. */
const DEFAULT_MAX_FILE_MB = 25;

/**
 * The machine code at the head of a job's error_detail, e.g.
 * "PARSE_FAILED: no text could be extracted" -> "PARSE_FAILED".
 *
 * The worker stores one free-text column, so the code has to be split back out
 * before it can be translated. An entry with no separator is treated as the
 * code itself; anything else degrades to the generic Persian sentence rather
 * than showing the developer's English.
 */
function jobFailureCode(detail: string | null | undefined): string {
  if (!detail) return "EXTRACTION_FAILED";
  const code = detail.split(":", 1)[0].trim().toUpperCase();
  return /^[A-Z][A-Z0-9_]{2,}$/.test(code) ? code : "EXTRACTION_FAILED";
}

/**
 * GET /knowledge-sources -> a normalized list.
 *
 * The new contract is a LIST (a user may register several folders). An earlier
 * build answered a single object, and "no source" arrives as an empty object
 * rather than an empty list. Both are accepted here so the page keeps working
 * whichever shape the deployment has, without a second code path above.
 */
function normalizeSources(raw: unknown): SourceFolder[] {
  const rows: unknown[] = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && "id" in raw
      ? [raw]
      : [];
  const out: SourceFolder[] = [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const item = row as Record<string, unknown>;
    if (item.id === undefined || item.id === null) continue;
    // `discovered_files` is the list-shape field; `file_state` is what the
    // single-object payload used to carry.
    const files = item.discovered_files ?? item.file_state;
    out.push({
      id: String(item.id),
      path: String(item.path_label ?? item.path ?? ""),
      source_type: item.source_type === "client_folder" ? "client_folder" : "local_folder",
      status: String(item.status ?? ""),
      discovered_files: typeof files === "number" ? files : null,
      last_scanned_at: typeof item.last_scanned_at === "string" ? item.last_scanned_at : null,
      // A folder with no owner is the organization-wide one; a folder with an
      // owner belongs to that person.
      is_org: item.user_id === null || item.user_id === undefined,
    });
  }
  return out;
}

/** Files over the server's cap, by the cap the server advertised. */
function oversizeFiles(files: File[], limitMb: number): File[] {
  const maxBytes = limitMb * 1024 * 1024;
  return files.filter((file) => file.size > maxBytes);
}

/** ".pdf" from "Report.PDF" — the same shape the API's `extension` uses. */
function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

type TabKey = "all" | "ready" | "processing" | "queued" | "failed";
const PAGE_SIZE = 8;

/**
 * How often the screen re-reads the server while something is still moving.
 *
 * Two seconds is fast enough that an upload or a scan visibly advances without
 * the operator touching anything, and slow enough that an idle page costs
 * nothing — because on an idle page the poll is switched OFF entirely (see
 * POLLING below), not merely slowed.
 */
const POLL_MS = 2000;

/**
 * After a manual scan/sync the folder's own row can change (discovered count,
 * last scan time) even though the SOURCE status itself stays "active". Nothing
 * on the wire says "a scan is running", so the page watches the folder list for
 * a bounded window after the operator starts one, then settles.
 */
const SCAN_WATCH_MS = 30_000;

/**
 * Asset statuses the pipeline has finished with: no later request will change
 * them. Anything NOT in this set is treated as moving, which is the honest
 * default — an unknown new status keeps the page live rather than freezing it.
 */
const TERMINAL_ASSET = new Set([
  "ready",
  "indexed",
  "succeeded",
  "failed",
  "parse_failed",
  "cancelled",
  "skipped",
  "duplicate",
  "stopped",
  "deleted",
  "needs_review",
]);

/** A folder whose watch state will not move on its own. */
const TERMINAL_SOURCE = new Set(["active", "disabled"]);

function assetPending(a: Asset): boolean {
  return !TERMINAL_ASSET.has((a.status ?? "").toLowerCase());
}

function sourcePending(s: SourceFolder): boolean {
  return !TERMINAL_SOURCE.has((s.status ?? "").toLowerCase());
}

/**
 * A file the operator just handed over, shown BEFORE the server has answered
 * (B1).
 *
 * The upload used to be awaited inside the dialog, so the modal stayed open for
 * the whole transfer — the PO's complaint. The row is now rendered the instant
 * the request starts, marked «در حال بارگذاری», and replaced by the server's
 * own row (matched by id) once the list comes back.
 */
interface PendingUpload {
  key: string;
  file: File;
  name: string;
  size_bytes: number;
  extension: string;
  status: "uploading" | "failed";
  error?: string;
  /** Filled from the upload response, so the row is reconciled BY ID. */
  serverId?: string;
}

/** A table row: a server asset, or a just-started local upload. */
type Row = Asset & { local?: PendingUpload };

/** The server's answer to POST /knowledge-assets/upload. */
interface UploadResult {
  stored?: Array<{ id?: string; name?: string }>;
  rejected?: Array<{ name?: string; code?: string; message?: string }>;
}

/**
 * The server's answer to POST /knowledge-sources/{id}/scan.
 *
 * The endpoint returns the SOURCE payload spread together with the scan's own
 * result (backend knowledge/service.py: scan_source -> {**_payload, **result}),
 * so the counts live at the top level next to id/path/status. Every count is
 * optional here because an older deployment may answer the source payload
 * alone — the notice then says only what it actually knows.
 */
interface ScanResult {
  scan_type?: string;
  files_added?: number;
  files_updated?: number;
  files_deleted?: number;
  discovered_files?: number;
}

function countOf(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.max(0, Math.trunc(value));
}

/**
 * What the manual scan ACTUALLY did, in Persian.
 *
 * The button used to answer «پویش دستی اجرا شد.» no matter what came back, so a
 * scan of a folder the server cannot see read exactly like one that ingested
 * fifty files — the PO's complaint that «پویش اکنون» did not scan the folder.
 * The real numbers are in the response and are reported here; a run that found
 * nothing says so instead of looking like a success.
 */
function scanNotice(scan: ScanResult): string {
  const discovered = countOf(scan.discovered_files);
  const added = countOf(scan.files_added) ?? 0;
  const updated = countOf(scan.files_updated) ?? 0;
  const deleted = countOf(scan.files_deleted) ?? 0;
  if (discovered === 0) return "پویش انجام شد؛ پوشه هیچ فایل تازه‌ای نداشت.";
  const parts: string[] = [];
  if (discovered !== null) parts.push("پویش انجام شد: " + faNum(discovered) + " فایل بررسی شد");
  else parts.push("پویش انجام شد");
  if (added > 0) parts.push(faNum(added) + " فایل تازه اضافه شد");
  if (updated > 0) parts.push(faNum(updated) + " فایل تغییرکرده به‌روزرسانی شد");
  if (deleted > 0) parts.push(faNum(deleted) + " فایل حذف‌شده علامت خورد");
  if (added === 0 && updated === 0 && deleted === 0) parts.push("فایل تازه‌ای پیدا نشد");
  return parts.join("؛ ") + ".";
}

/**
 * The server's own percentage for one file, or null when it did not give one.
 *
 * Absence and null both mean "the server has not told us", which is NOT zero:
 * rendering ۰٪ for a file the server never measured would be an invented fact,
 * so every caller below falls back to the stage label instead.
 */
function progressValue(asset: Asset): number | null {
  const raw = asset.progress;
  if (typeof raw !== "number" || !Number.isFinite(raw)) return null;
  return Math.max(0, Math.min(100, Math.round(raw)));
}

/**
 * The server's stage code -> the Persian label the operator reads.
 *
 * The stage string is the server's, so a code this build does not know is not
 * guessed at and NOT shown raw: an unknown English token would be worse than
 * the derived Persian sentence, which is what happens then.
 */
const STAGE_LABELS: Record<string, string> = {
  queued: "در صف پردازش",
  pending: "در صف پردازش",
  discovered: "تازه شناسایی شد",
  uploading: "در حال بارگذاری",
  uploaded: "بارگذاری شد",
  extracting: "استخراج متن",
  extraction: "استخراج متن",
  text: "استخراج متن",
  ocr: "تشخیص متن تصویری",
  extracted: "متن استخراج شد",
  text_extracted: "متن استخراج شد",
  chunking: "تقسیم به واحد دانش",
  chunked: "تقسیم به واحد دانش",
  embedding: "ساخت بردار معنایی",
  embedded: "ساخت بردار معنایی",
  indexing: "نمایه‌سازی",
  indexed: "نمایه‌سازی",
  classifying: "دسته‌بندی",
  classify: "دسته‌بندی",
  finalizing: "آماده‌سازی نهایی",
};

function stageLabel(stage: string | null | undefined): string | null {
  if (!stage) return null;
  return STAGE_LABELS[stage.trim().toLowerCase()] ?? null;
}

/** The furthest stage the row's own fields reveal, when the server sent none. */
function derivedStage(asset: Asset): string {
  const textLength = asset.text_length ?? 0;
  if (textLength > 0) return asset.pipeline ? "متن استخراج شد" : "در حال پردازش";
  return "در صف پردازش";
}

/**
 * The highest percentage seen for each still-running file.
 *
 * Polls are independent samples of one attempt and a later sample can lag
 * behind an earlier one (a dropped response, a job that restarts its stage), so
 * a bar that followed the newest number would rewind on its own. The CEILING is
 * what gets rendered instead, keyed by asset id. The entry is dropped once the
 * row reaches a terminal state: that attempt is over, and a file re-queued
 * afterwards is a NEW attempt whose numbers may legitimately start over.
 */
function useProgressCeiling(assets: Asset[]): Map<string, number> {
  const [ceiling, setCeiling] = useState<Record<string, number>>({});
  useEffect(() => {
    setCeiling((previous) => {
      const next: Record<string, number> = {};
      let changed = false;
      for (const asset of assets) {
        // A terminal row has finished this attempt: forgetting it lets a file
        // that is re-queued later start over from its own new numbers.
        if (!assetPending(asset)) continue;
        const before = previous[asset.id];
        const value = Math.max(before ?? 0, progressValue(asset) ?? 0);
        next[asset.id] = value;
        if (before === undefined || before !== value) changed = true;
      }
      for (const id of Object.keys(previous)) if (!(id in next)) changed = true;
      // Same numbers as last time: return the SAME object, so a poll that
      // repeats itself cannot cause a render loop.
      return changed ? next : previous;
    });
  }, [assets]);
  return useMemo(() => new Map(Object.entries(ceiling)), [ceiling]);
}

/**
 * What a document is doing inside the pipeline (H2 + PO request).
 *
 * The document table used to show only a coarse status, so a file waiting its
 * turn and one that had already been read but not split into knowledge units
 * looked identical — an operator could not tell whether a stuck queue was
 * moving. The stage label still covers every file; on top of it, the server now
 * reports a percentage for a file that is still being prepared, and that is
 * rendered as a real bar plus the Persian number.
 *
 * The percentage is NEVER invented: without one from the server the column
 * falls back to the stage label exactly as before.
 */
function AssetProgress({ asset }: { asset: Asset }) {
  if (asset.status === "failed") {
    return <span className="text-micro text-muted-foreground">متوقف — به خطا رسید</span>;
  }
  if (asset.status === "ready") {
    const chunks = asset.chunks ?? 0;
    return (
      <span data-numeric className="text-micro text-muted-foreground">
        {chunks > 0 ? faNum(chunks) + " واحد دانش" : "بدون واحد دانش"}
      </span>
    );
  }
  // Still in the queue or being worked on: report the furthest stage reached.
  const textLength = asset.text_length ?? 0;
  const stage = textLength > 0 ? (asset.pipeline ? "متن استخراج شد" : "در حال پردازش") : "در صف پردازش";
  return (
    <span className="text-micro text-muted-foreground">
      {stage}
      {textLength > 0 && (
        <span data-numeric className="ms-1 opacity-75">
          · {faNum(textLength)} نویسه
        </span>
      )}
    </span>
  );
}

/**
 * The row's progress cell (PO request: a percentage per file).
 *
 * While a file is being prepared AND the server gave a percentage, this renders
 * a real progress bar plus the Persian number («۴۰٪») and the Persian stage
 * name, and says in words that the file cannot answer questions yet. That last
 * sentence is the PO's other report: a file that was still being read looked
 * exactly like a file that was never added, so a question asked meanwhile came
 * back with «سندی وجود نداشت».
 *
 * When the server gave no percentage — null, absent, or a row the pipeline has
 * finished with — this falls straight back to the stage label, so no number is
 * ever invented from an unknown denominator.
 */
function AssetPreparation({ asset, ceiling }: { asset: Asset; ceiling: Map<string, number> }) {
  const reported = progressValue(asset);
  if (reported === null || !assetPending(asset)) return <AssetProgress asset={asset} />;
  // Monotonic within one attempt: never below the highest value already seen.
  const value = Math.max(reported, ceiling.get(asset.id) ?? 0);
  const stage = stageLabel(asset.stage) ?? derivedStage(asset);
  return (
    <div className="min-w-[168px] space-y-1" data-testid={"asset-percent-" + asset.id}>
      <div className="flex items-center justify-between gap-2 text-micro">
        <span data-numeric className="font-semibold text-warning">
          {faNum(value)}٪
        </span>
        <span className="text-muted-foreground">{stage}</span>
      </div>
      {/* The house progressbar markup (OrgDetailPanel): role + aria-valuenow on
          the element itself. The shared <Progress> wrapper drops Radix's value
          prop, so its bar would carry no aria-valuenow at all. */}
      <div
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={"پیشرفت آماده‌سازی " + asset.name}
        className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
      >
        <div className="h-full rounded-full bg-warning" style={{ width: value + "%" }} />
      </div>
      <span className="block text-micro text-warning">
        در حال آماده‌سازی — هنوز آمادهٔ پاسخ‌دهی نیست.
      </span>
    </div>
  );
}

export default function Knowledge() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sources, setSources] = useState<SourceFolder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<TabKey>("all");
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState("all");
  const [page, setPage] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [picked, setPicked] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [maxFileMb, setMaxFileMb] = useState<number | null>(null);
  // B1: rows for files whose upload is in flight (or has failed). They are shown
  // before the server's list knows anything about them.
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  // Bounded watch window opened when the operator starts a scan/sync.
  const [scanWatchUntil, setScanWatchUntil] = useState(0);
  // The folder row AS IT STOOD when that action started, so the window's end can
  // tell the operator whether anything actually moved.
  const scanBaseline = useRef<{ id: string; discovered: number | null; scannedAt: string | null } | null>(
    null,
  );
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadSeq = useRef(0);

  const [loadError, setLoadError] = useState<string | null>(null);
  // The browser build has no native folder picker and no local file access.
  const desktop = isDesktop();

  const reload = useCallback(async () => {
    const [a, j, s] = await Promise.all([
      // The asset router moved off "/knowledge" to "/knowledge-assets" when the
      // source router was split out, and this page was left calling the old
      // prefix - so every one of these four calls 404'd. The unit suite stubbed
      // the same wrong string, which is exactly why it stayed green.
      api<{ assets: Asset[] }>("GET", "/knowledge-assets"),
      api<{ jobs: Job[] }>("GET", "/processing/jobs"),
      api<unknown>("GET", "/knowledge-sources"),
    ]);
    setAssets(a.assets ?? []);
    setJobs(j.jobs ?? []);
    setSources(normalizeSources(s));
    setLoadError(null);
  }, []);

  // P1-5: the server's own per-file cap, read ONCE from the sync plan and used
  // to reject oversize files in the picker instead of uploading them first and
  // learning about the limit from a 413. Failure to read it is not an error:
  // the dropzone falls back to the documented default.
  const loadLimit = useCallback(async () => {
    try {
      const plan = await api<{ max_file_mb?: number }>("GET", "/knowledge-sources/client-folder/sync-plan");
      if (typeof plan.max_file_mb === "number" && plan.max_file_mb > 0) setMaxFileMb(plan.max_file_mb);
    } catch {
      // Keep the default; the upload route still enforces the real cap.
    }
  }, []);

  // PO request: the server's Persian reason stays visible and a retry button
  // replaces the empty page when the first load fails.
  const refresh = useCallback(async () => {
    try {
      await reload();
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "دریافت وضعیت دانش ناموفق بود.");
    }
  }, [reload]);

  useEffect(() => {
    void refresh();
    void loadLimit();
  }, [refresh, loadLimit]);

  // POLLING (B2). Two independent polls — the document list and the folder list
  // — and each one runs ONLY while its side still has something non-terminal:
  // an upload in flight, a document the pipeline has not finished with, or the
  // bounded window after a manual scan. Passing `null` tears the interval down,
  // so an idle page pays for no timer at all instead of polling forever.
  const watchingScans = Date.now() < scanWatchUntil;
  const pollAssets =
    pendingUploads.some((p) => p.status === "uploading") || anyPending(assets, assetPending);
  const pollSources = watchingScans || anyPending(sources, sourcePending);

  const liveAssets = useLive<{ assets?: Asset[] }>(pollAssets ? "/knowledge-assets" : null, POLL_MS);
  const liveSources = useLive<unknown>(pollSources ? "/knowledge-sources" : null, POLL_MS);

  // A failed poll never lands here (the hook keeps the previous payload), so the
  // list is only ever replaced by data the server actually sent — a dropped
  // request can neither blank the table nor reset the paging the user is on.
  useEffect(() => {
    if (liveAssets.data) setAssets(liveAssets.data.assets ?? []);
  }, [liveAssets.data]);

  useEffect(() => {
    if (liveSources.data !== null) setSources(normalizeSources(liveSources.data));
  }, [liveSources.data]);

  // What the bounded scan watch does when it closes (PO request).
  //
  // Nothing on the wire says "a scan is running", so the only evidence a manual
  // scan did anything is the folder's own discovered count / last-scan time
  // moving. If the window closes and NEITHER moved, the page says so out loud:
  // a silent return to idle is exactly how a scan that found nothing used to
  // look like one that worked.
  useEffect(() => {
    if (scanWatchUntil === 0) return;
    const timer = setTimeout(() => {
      const baseline = scanBaseline.current;
      scanBaseline.current = null;
      setScanWatchUntil(0);
      if (!baseline) return;
      const current = sources.find((s) => s.id === baseline.id);
      if (!current) return;
      if (
        current.discovered_files === baseline.discovered &&
        current.last_scanned_at === baseline.scannedAt
      ) {
        setNotice(
          "پویش تمام شد ولی چیزی در این پوشه تغییر نکرد: نه فایل تازه‌ای شناسایی شد و نه زمان پویش به‌روز شد. اگر انتظار فایل تازه‌ای داشتید، نشانی پوشه و دسترسی سرور به آن را بررسی کنید.",
        );
      }
    }, Math.max(0, scanWatchUntil - Date.now()));
    return () => clearTimeout(timer);
  }, [scanWatchUntil, sources]);

  // Optimistic rows are reconciled BY ID: as soon as the server lists the asset
  // whose id the upload answered with, the local row is dropped, so the same
  // file is never on screen twice even when the server assigned its own id.
  useEffect(() => {
    if (pendingUploads.length === 0) return;
    setPendingUploads((prev) => {
      const next = prev.filter(
        (p) =>
          !(
            p.status === "uploading" &&
            (p.serverId ? assets.some((a) => a.id === p.serverId) : assets.some((a) => a.name === p.name))
          ),
      );
      return next.length === prev.length ? prev : next;
    });
  }, [assets, pendingUploads.length]);

  const limitMb = maxFileMb ?? DEFAULT_MAX_FILE_MB;

  /** Reject the files the server will refuse anyway - before any byte is sent. */
  function acceptedFiles(files: File[]): File[] {
    const tooBig = oversizeFiles(files, limitMb);
    if (tooBig.length === 0) return files;
    setError(
      "این فایل‌ها از حد مجاز " +
        faNum(limitMb) +
        " مگابایت بزرگ‌ترند و اضافه نشدند: " +
        tooBig.map((f) => f.name).join("، "),
    );
    const blocked = new Set(tooBig.map((f) => f.name + ":" + f.size));
    return files.filter((f) => !blocked.has(f.name + ":" + f.size));
  }

  function pickFiles(files: File[]) {
    setError(null);
    setPicked((prev) => [...prev, ...acceptedFiles(files)]);
  }

  /**
   * B1: START the upload and close the dialog, without waiting for it.
   *
   * This used to be `await api(...)` followed by the close, so the operator sat
   * inside the modal for the whole transfer and only then saw the modal go away.
   * The confirmation now does only what it says: the rows appear in the table
   * immediately as «در حال بارگذاری», the dialog closes on the same click, and
   * the request finishes on its own — the live poll then reports whatever the
   * server says next (queued -> processing -> ready/failed).
   *
   * The client-side size gate has already run in `pickFiles` (P1-5), before any
   * of this, so nothing reaches the network that the picker refused.
   */
  function upload() {
    const files = picked;
    if (files.length === 0) {
      setError("ابتدا فایل را انتخاب کنید.");
      return;
    }
    const rows: PendingUpload[] = files.map((file) => ({
      key: "upload-" + ++uploadSeq.current,
      file,
      name: file.name,
      size_bytes: file.size,
      extension: extensionOf(file.name),
      status: "uploading",
    }));
    setError(null);
    setNotice(null);
    // Reset the picker here as well as on close, so reopening the dialog can
    // never resend the selection that was just confirmed.
    setPicked([]);
    setDialogOpen(false);
    setPendingUploads((prev) => [...prev, ...rows]);
    for (const row of rows) void sendUpload(row);
  }

  /**
   * Send ONE row.
   *
   * One request per file keeps a failure attached to the file that caused it and
   * gives each failed row its own retry, instead of one batch failure that
   * cannot say which of five files the server refused.
   */
  async function sendUpload(row: PendingUpload) {
    const form = new FormData();
    form.append("files", row.file);
    try {
      const result = await api<UploadResult>("POST", "/knowledge-assets/upload", form);
      const stored = Array.isArray(result?.stored) ? result.stored : [];
      const rejected = Array.isArray(result?.rejected) ? result.rejected : [];
      const match = stored.find((s) => s?.name === row.name);
      const refusal = rejected.find((r) => r?.name === row.name);
      if (match) {
        setNotice("فایل در صف پردازش قرار گرفت.");
        // Keep the row until the server's own list carries this id; the effect
        // above then removes it. That is the by-id reconciliation.
        setPendingUploads((prev) =>
          prev.map((p) =>
            p.key === row.key ? { ...p, serverId: match.id ? String(match.id) : undefined } : p,
          ),
        );
      } else {
        // The server answered but neither stored nor rejected this name: the row
        // stays on screen as a failure rather than disappearing silently.
        setPendingUploads((prev) =>
          prev.map((p) =>
            p.key === row.key
              ? { ...p, status: "failed", error: persianError(refusal?.code ?? "", 0, refusal?.message ?? null) }
              : p,
          ),
        );
      }
      await reload();
    } catch (exc) {
      // D6: keep the server's reason (size cap, format, quota) instead of a
      // generic message that hides it — and never drop the file.
      setPendingUploads((prev) =>
        prev.map((p) =>
          p.key === row.key
            ? { ...p, status: "failed", error: exc instanceof ApiError ? exc.message : "آپلود ناموفق بود." }
            : p,
        ),
      );
    }
  }

  /** Re-send one failed row, from the file the page kept for exactly this. */
  function retryUpload(row: PendingUpload) {
    setError(null);
    setNotice(null);
    setPendingUploads((prev) =>
      prev.map((p) => (p.key === row.key ? { ...p, status: "uploading", error: undefined } : p)),
    );
    void sendUpload(row);
  }

  /** Drop a failed row the operator has decided not to retry. */
  function dismissUpload(key: string) {
    setPendingUploads((prev) => prev.filter((p) => p.key !== key));
  }

  /**
   * Register ANOTHER folder. The server validates the path and reuses the row
   * only when the identical path is already registered, so calling this against
   * an existing folder is idempotent while a new path appends.
   */
  async function addFolder() {
    const path = newPath.trim();
    if (!path) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api("POST", "/knowledge-sources", { path });
      setNotice("پوشهٔ جدید ثبت شد و در پویش بعدی پردازش می‌شود.");
      setNewPath("");
      setAddOpen(false);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "ثبت پوشه ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  /** Native picker for the desktop build; a no-op in the browser. */
  async function chooseLocalFolder() {
    const chosen = await pickFolder();
    if (chosen) setNewPath(chosen);
  }

  /**
   * Per-folder action, branching on `source_type` (P0-3).
   *
   * `local_folder` is a path ON THE SERVER, so POST /{id}/scan is the right
   * call. A `client_folder` lives on the person's own machine and the server
   * can never read it: that endpoint always answers 400
   * INGESTION_PATH_NOT_READABLE, which is exactly the dead button the audit
   * found. For those folders we drive the client-side sync instead, and only on
   * the desktop build, which is the only place the folder's bytes exist.
   */
  async function runFolderAction(folder: SourceFolder) {
    setBusy(true);
    setError(null);
    setNotice(null);
    // A folder the server can never read: refuse before opening a watch window
    // that would have nothing to watch.
    if (folder.source_type === "client_folder" && !desktop) {
      setError("این پوشه روی رایانهٔ شماست؛ همگام‌سازی آن از برنامهٔ ویندوزی HiveOS انجام می‌شود.");
      setBusy(false);
      return;
    }
    // B2: the scan's own result (discovered count, last scan time) lands while
    // the SOURCE status stays "active", so watch the folder list for a bounded
    // window after the operator starts one instead of polling it forever. The
    // row AS IT WAS is remembered beside the window: if the window closes and
    // neither count moved, the operator is told that the scan changed nothing
    // (see the effect below) rather than being left to guess.
    scanBaseline.current = {
      id: folder.id,
      discovered: folder.discovered_files,
      scannedAt: folder.last_scanned_at,
    };
    setScanWatchUntil(Date.now() + SCAN_WATCH_MS);
    try {
      if (folder.source_type === "client_folder") {
        const result = await syncClientFolder(folder.path, undefined, limitMb);
        setNotice(
          "همگام‌سازی انجام شد: " +
            faNum(result.discovered_files) +
            " فایل شناسایی شد" +
            (result.rejected.length + result.failed.length > 0
              ? " و " + faNum(result.rejected.length + result.failed.length) + " فایل رد شد"
              : "") +
            ".",
        );
      } else {
        // The scan answers with the source payload PLUS its own result, so the
        // notice is built from the response instead of a fixed sentence.
        const scan = await api<ScanResult>("POST", "/knowledge-sources/" + folder.id + "/scan");
        setNotice(scanNotice(scan));
      }
      await reload();
    } catch (e) {
      // The server's own reason (ApiError.message), never a generic success.
      setError(e instanceof Error ? e.message : "اجرای این کار ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  /** US-201 FR-008: disable / re-enable one folder without touching the rest. */
  async function toggleFolder(folder: SourceFolder) {
    const next = folder.status === "active" ? "disabled" : "active";
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api("PUT", "/knowledge-sources/" + folder.id, { status: next });
      setNotice(next === "active" ? "پوشه فعال شد." : "پوشه غیرفعال شد.");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "تغییر وضعیت پوشه ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  /**
   * US-201 FR-008 parity: removing a folder stops it feeding the knowledge base.
   *
   * Disabling is the reversible half and always works; the hard delete is only
   * requested when the route exists. A 404/405 means this deployment has no
   * delete yet, so the folder is disabled instead and the user is told that -
   * rather than the page pretending the folder is gone while its scans keep
   * running.
   */
  async function removeFolder(folder: SourceFolder) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api("DELETE", "/knowledge-sources/" + folder.id);
      setNotice("پوشه حذف شد.");
    } catch (e) {
      const routeMissing = e instanceof ApiError && (e.status === 404 || e.status === 405);
      if (routeMissing) {
        try {
          await api("PUT", "/knowledge-sources/" + folder.id, { status: "disabled" });
          setNotice("حذف پوشه در این نسخه پشتیبانی نمی‌شود؛ پوشه غیرفعال شد و دیگر پویش نمی‌شود.");
        } catch (inner) {
          setError(inner instanceof Error ? inner.message : "غیرفعال‌کردن پوشه ناموفق بود.");
        }
      } else {
        setError(e instanceof Error ? e.message : "حذف پوشه ناموفق بود.");
      }
    } finally {
      await reload();
      setBusy(false);
    }
  }

  async function classify(assetId: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api("POST", "/knowledge-assets/" + assetId + "/classify");
      setNotice("دسته‌بندی سند اجرا شد.");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "دسته‌بندی ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  /**
   * Fetch the bytes and hand them to the browser.
   *
   * The download route is authenticated, so a plain <a href> would arrive
   * without the bearer token. Fetching through the api client and turning the
   * response into an object URL keeps the request authenticated and still ends
   * in the browser's own download UI, with the server's filename.
   */
  async function download(assetId: string, name: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken();
      const response = await fetch(`${API_BASE}/knowledge-assets/${assetId}/download`, {
        headers: token ? { Authorization: "Bearer " + token } : {},
      });
      if (!response.ok) throw new Error("دانلود فایل ناموفق بود.");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "دانلود فایل ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  const jobByAsset = new Map<string, Job>();
  for (const j of jobs) if (j.asset_id) jobByAsset.set(j.asset_id, j);

  /**
   * What the table renders: rows whose upload is still local first, then
   * everything the server lists. Same shape, so the table, the filters and the
   * paging need no second code path.
   */
  const rows: Row[] = useMemo(
    () => [
      ...pendingUploads.map((p) => ({
        id: p.serverId ?? p.key,
        name: p.name,
        status: p.status,
        size_bytes: p.size_bytes,
        extension: p.extension,
        origin: "upload",
        local: p,
      })),
      ...assets,
    ],
    [pendingUploads, assets],
  );

  // Monotonic progress per file (see useProgressCeiling): read during render,
  // advanced after it, so a poll can never rewind a bar.
  const progressCeiling = useProgressCeiling(assets);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length, ready: 0, processing: 0, queued: 0, failed: 0 };
    for (const a of rows) if (c[a.status] !== undefined) c[a.status] += 1;
    return c;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = norm(search);
    return rows.filter((a) => {
      if (tab !== "all" && a.status !== tab) return false;
      if (format !== "all" && (a.extension ?? "").replace(".", "").toLowerCase() !== format) return false;
      if (q && !norm(a.name).includes(q)) return false;
      return true;
    });
  }, [rows, tab, search, format]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const formats = useMemo(
    () => Array.from(new Set(rows.map((a) => (a.extension ?? "").replace(".", "").toLowerCase()).filter(Boolean))),
    [rows],
  );
  const readyCount = counts.ready;
  const activeCount = counts.processing + counts.queued;
  // A file that is not ready yet cannot answer a question. Counting them here
  // lets the page say so in words near the document list (PO report: a file was
  // added, the answer still said no document was found in the context).
  const preparingRows = rows.filter((a) =>
    a.local ? a.local.status === "uploading" : assetPending(a),
  );

  return (
    <section aria-label="دانش سازمان">
      {/* page-head (mockup) */}
      <div className="mb-5 flex flex-wrap items-start gap-3.5">
        <div>
          <h1 className="text-title text-foreground">دانش سازمان</h1>
          <p className="mt-[3px] text-caption text-muted-foreground">
            پوشه‌ها، وضعیت پردازش و جستجو در اسناد — همه در یک صفحه. هر پوشه‌ای که اضافه می‌کنید به همان دانش
            سازمان اضافه می‌شود و پوشه‌های قبلی سر جای خودشان می‌مانند.
          </p>
        </div>
        <div className="ms-auto flex items-center gap-2">
          <LoadingButton size="sm" variant="secondary" onClick={() => setAddOpen(true)} data-testid="add-folder">
            <FolderPlus aria-hidden />
            افزودن پوشه جدید
          </LoadingButton>
          <LoadingButton size="sm" onClick={() => setDialogOpen(true)}>
            افزودن سند
          </LoadingButton>
        </div>
      </div>

      {notice && (
        <div className="mb-4">
          <Banner tone="success" data-testid="knowledge-notice">{notice}</Banner>
        </div>
      )}
      {error && (
        <div className="mb-4">
          <Banner tone="error" data-testid="knowledge-error">{error}</Banner>
        </div>
      )}
      {loadError && (
        <div className="mb-4">
          <RetryNotice
            message={loadError}
            onRetry={() => void refresh()}
            testId="knowledge-retry"
            compact
          />
        </div>
      )}

      {/* پوشه‌های ثبت‌شده — one card per folder (PO request). */}
      <h2 className="mb-3 text-heading text-foreground">پوشه‌های دانش</h2>
      {/* PO rule that decides the whole access model: the folder you add is NOT
          the limit on what you can read. Stated in copy so a member is not
          surprised when a colleague's folder answers their question. */}
      <Banner tone="info" className="mb-4">
        هر پوشه‌ای که ثبت می‌کنید به دانش مشترک سازمان اضافه می‌شود. این که هر کس چه چیزی را می‌تواند بخواند
        به سطح دسترسی او بستگی دارد، نه به این‌که پوشه را چه کسی اضافه کرده است؛ مدیران سازمان همهٔ پوشه‌ها را
        می‌خوانند.
      </Banner>

      {sources.length === 0 ? (
        <Surface className="mb-4 p-6" data-testid="folders-empty">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="flex size-11 shrink-0 items-center justify-center rounded-control bg-amber-soft text-amber"
            >
              <FolderOpen className="size-5" />
            </span>
            <div>
              <div className="text-body font-bold text-foreground">هنوز پوشه‌ای ثبت نشده است.</div>
              <div className="mt-1 text-caption text-muted-foreground">
                پوشهٔ اسناد را ثبت کنید تا پردازش آغاز شود. بعد از آن می‌توانید هر تعداد پوشهٔ دیگر اضافه کنید.
                برای شروع، «افزودن پوشه جدید» را از بالای همین صفحه بزنید.
              </div>
            </div>
          </div>
        </Surface>
      ) : (
        <div className="mb-4 space-y-3">
          {sources.map((folder) => {
            const isClient = folder.source_type === "client_folder";
            return (
              <Surface key={folder.id} className="p-5" data-testid={"folder-" + folder.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span
                      aria-hidden
                      className="flex size-11 shrink-0 items-center justify-center rounded-control bg-amber-soft text-amber"
                    >
                      <FolderOpen className="size-5" />
                    </span>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-body font-bold text-foreground">
                          {folder.is_org ? "پوشهٔ سازمان" : "پوشهٔ من"}
                        </span>
                        <span
                          data-testid={"folder-kind-" + folder.id}
                          className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5 text-micro text-muted-foreground"
                        >
                          {isClient ? <MonitorSmartphone aria-hidden className="size-3.5" /> : <Server aria-hidden className="size-3.5" />}
                          {isClient ? "روی رایانهٔ شما" : "روی سرور"}
                        </span>
                      </div>
                      <div className="mt-1 font-mono text-caption text-muted-foreground" dir="ltr">
                        {folder.path}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    {/* The watch state is a health signal, not a knowledge
                        status: "active" here means the scheduled scan runs. */}
                    <DomainStatus domain="source" value={folder.status} dot />
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-caption text-muted-foreground">
                  <span data-testid={"folder-files-" + folder.id}>
                    فایل‌های شناسایی‌شده: {folder.discovered_files === null ? "نامشخص" : faNum(folder.discovered_files)}
                  </span>
                  <span data-testid={"folder-scanned-" + folder.id}>
                    آخرین پویش: {folder.last_scanned_at ? faDateTime(folder.last_scanned_at) : "هنوز انجام نشده"}
                  </span>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {/* P0-3: the scan control must never be a button that is
                      guaranteed to fail. A client folder is walked by the
                      person's own machine, so the control becomes the
                      client-side sync (and is only offered where the folder
                      actually exists). */}
                  <LoadingButton
                    variant="secondary"
                    size="sm"
                    loading={busy}
                    disabled={busy || folder.status !== "active" || (isClient && !desktop)}
                    onClick={() => void runFolderAction(folder)}
                    data-testid={"folder-scan-" + folder.id}
                    title={isClient && !desktop ? "این پوشه روی رایانهٔ شماست" : undefined}
                  >
                    <RefreshCw aria-hidden />
                    {isClient ? "همگام‌سازی اکنون" : "پویش اکنون"}
                  </LoadingButton>
                  <LoadingButton
                    variant="secondary"
                    size="sm"
                    loading={busy}
                    disabled={busy}
                    onClick={() => void toggleFolder(folder)}
                    data-testid={"folder-toggle-" + folder.id}
                  >
                    <Power aria-hidden />
                    {folder.status === "active" ? "غیرفعال‌کردن" : "فعال‌کردن"}
                  </LoadingButton>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => void removeFolder(folder)}
                    data-testid={"folder-remove-" + folder.id}
                    className="text-error hover:bg-error-bg hover:text-error"
                  >
                    <Trash2 aria-hidden />
                    حذف پوشه
                  </Button>
                </div>

                <div className="mt-3">
                  <Banner tone={isClient ? "info" : "plain"}>
                    {isClient
                      ? "این پوشه روی رایانهٔ خودتان است و سرور به آن دسترسی ندارد؛ همگام‌سازی از برنامهٔ HiveOS روی رایانهٔ شما انجام می‌شود. برای پردازش فوری «همگام‌سازی اکنون» را بزنید."
                      : "فایل‌های تازه‌ای که در این پوشه روی سرور قرار می‌دهید، در پویش بعدی (حداکثر ۳۰ دقیقه) شناسایی و پردازش می‌شوند. برای پردازش فوری «پویش اکنون» را بزنید."}
                  </Banner>
                </div>
              </Surface>
            );
          })}
        </div>
      )}

      {/* آمار (stat-card, mockup §۲۱) */}
      <div className="mb-4 grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <StatCard label="کل اسناد" value={faNum(rows.length)} />
        <StatCard label="آماده برای گفتگو" value={faNum(readyCount)} />
        <StatCard label="در حال پردازش" value={faNum(activeCount)} tone={activeCount > 0 ? "info" : undefined} />
        <StatCard label="ناموفق" value={faNum(counts.failed)} tone={counts.failed > 0 ? "danger" : undefined} />
      </div>

      {/* Status filters (mockup §۱۷).
          These were Tabs, which was the wrong control and also broken: Radix
          gives every trigger an aria-controls pointing at a matching
          TabsContent panel, and there were no panels at all, so all five
          triggers referenced elements that do not exist (axe:
          aria-valid-attr-value, critical). They do not switch between panels
          either — they narrow one table — so they are a pressed-state filter
          group, the pattern Wallet and EventsView already use. */}
      <Surface className="mb-4 p-4">
        <div role="group" aria-label="فیلتر وضعیت سند" className="flex flex-wrap items-center gap-1.5">
          {([
            ["all", "همه", counts.all],
            ["ready", "تکمیل شد", counts.ready],
            ["processing", "در حال پردازش", counts.processing],
            ["queued", "در صف", counts.queued],
            ["failed", "ناموفق", counts.failed],
          ] as Array<[TabKey, string, number]>).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              aria-pressed={tab === key}
              onClick={() => { setTab(key); setPage(0); }}
              className={cn(
                "inline-flex cursor-pointer items-center gap-1.5 rounded-control border px-2.5 py-1 text-body font-semibold transition-colors",
                tab === key
                  ? "border-primary bg-accent text-primary"
                  : "border-border bg-card text-muted-foreground hover:border-primary/40 hover:bg-accent/50",
              )}
            >
              {label}
              <CountChip value={count} />
            </button>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-3">
          <div className="relative min-w-[220px] flex-1">
            <Search aria-hidden className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="جستجو در اسناد…"
              aria-label="جستجوی اسناد"
              className="ps-9"
            />
          </div>
          <Select value={format} onValueChange={(v) => { setFormat(v); setPage(0); }}>
            <SelectTrigger
              aria-label="فیلتر فرمت"
              className="h-[42px] w-[150px] rounded-control border-border bg-card text-body text-muted-foreground"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">همه فرمت‌ها</SelectItem>
              {formats.map((f) => (
                <SelectItem key={f} value={f}>
                  {f.toUpperCase()}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </Surface>

      {/* PO report: «فایل اضافه کردم ولی می‌گوید سندی وجود نداشت». A file that is
          still being prepared cannot answer a question yet, so the page says so
          here, in words, next to the list — no modal, no blocking step. */}
      {preparingRows.length > 0 && (
        <Banner tone="warning" className="mb-4" data-testid="knowledge-preparing">
          {faNum(preparingRows.length)} سند هنوز در حال آماده‌سازی است و آمادهٔ پاسخ‌دهی نیست. تا پایان
          پردازش، پاسخ‌ها فقط از اسناد آماده ساخته می‌شوند؛ برای همین ممکن است دربارهٔ این فایل‌ها هنوز
          سندی پیدا نشود.
        </Banner>
      )}

      {/* جدول اسناد (mockup §۸) */}
      <Surface className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-border text-caption text-muted-foreground">
              <TableHead className="p-3 ps-5 font-bold">نام سند</TableHead>
              <TableHead className="p-3 font-bold">فرمت</TableHead>
              <TableHead className="p-3 font-bold">حجم</TableHead>
              <TableHead className="p-3 font-bold">وضعیت</TableHead>
              <TableHead className="p-3 font-bold">پیشرفت</TableHead>
              {/* The action column still needs a name: an empty <th> leaves the
                  cell unlabelled for screen readers (axe: empty-table-header). */}
              <TableHead className="p-3 pe-5 font-bold">
                <span className="sr-only">اقدام</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageItems.map((a) => {
              const job = jobByAsset.get(a.id);
              const local = a.local;
              const failedReason =
                local !== undefined
                  ? (local.error ?? "")
                  : a.status === "failed"
                    ? persianError(jobFailureCode(job?.error_detail))
                    : "";
              // The optimistic row keeps its own local key: for one render it
              // coexists with the server's row for the same id.
              return (
                <TableRow key={local ? local.key : a.id} className="border-border last:border-0">
                  <TableCell className="p-3 ps-5 font-bold whitespace-normal text-foreground" data-testid="asset-name">
                    {a.name}
                  </TableCell>
                  <TableCell className="p-3">
                    <span className="inline-block rounded-xs border border-border bg-secondary px-2 py-0.5 font-mono text-micro text-muted-foreground" dir="ltr">
                      {(a.extension ?? "").toUpperCase()}
                    </span>
                  </TableCell>
                  <TableCell className="p-3 font-mono text-caption text-muted-foreground" dir="ltr">
                    {humanSize(a.size_bytes)}
                  </TableCell>
                  <TableCell className="p-3" data-testid={"asset-status-" + a.status}>
                    {/* B1: a file the operator just handed over is not on the
                        server's list yet, and "uploading" is a state the API
                        never reports — so it is labelled here, explicitly, in
                        the same badge the server's own statuses use. */}
                    {a.local ? (
                      <StatusBadge
                        tone={a.local.status === "failed" ? "error" : "info"}
                        dot
                        title={a.local.status === "failed" ? "بارگذاری این فایل ناموفق بود." : "در حال ارسال به سرور…"}
                      >
                        {a.local.status === "failed" ? "ناموفق" : "در حال بارگذاری"}
                      </StatusBadge>
                    ) : (
                      <DomainStatus domain="asset" value={a.status} dot />
                    )}
                    {failedReason && (
                      <div className="mt-1 text-micro leading-relaxed text-error">{failedReason}</div>
                    )}
                  </TableCell>
                  {/* H2 + PO percentage request: what the document is actually
                      doing. A file that has been extracted but not chunked reads
                      differently from one that has not been touched, and a file
                      the server can measure shows a real bar and number. */}
                  <TableCell className="p-3" data-testid={"asset-progress-" + a.id}>
                    {a.local ? (
                      <span className="text-micro text-muted-foreground">
                        {a.local.status === "uploading" ? "در حال ارسال به سرور…" : "بارگذاری ناتمام ماند"}
                      </span>
                    ) : (
                      <AssetPreparation asset={a} ceiling={progressCeiling} />
                    )}
                  </TableCell>
                  <TableCell className="p-3 pe-5 text-end">
                    {local?.status === "failed" && (
                      <span className="inline-flex items-center gap-1">
                        <LoadingButton
                          variant="secondary"
                          size="xs"
                          onClick={() => retryUpload(local)}
                          data-testid={"upload-retry-" + local.name}
                        >
                          تلاش مجدد
                        </LoadingButton>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          aria-label={"حذف " + local.name + " از فهرست"}
                          onClick={() => dismissUpload(local.key)}
                        >
                          <X className="size-4" aria-hidden />
                        </Button>
                      </span>
                    )}
                    {a.status === "ready" && !local && (
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`دانلود ${a.name}`}
                        disabled={busy}
                        onClick={() => void download(a.id, a.name)}
                      >
                        <Download className="size-4" aria-hidden />
                      </Button>
                    )}
                    {a.status === "queued" && (
                      <LoadingButton variant="secondary" size="xs" onClick={() => classify(a.id)} disabled={busy}>
                        دسته‌بندی
                      </LoadingButton>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {pageItems.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="p-0">
                  <div className="px-5 py-12 text-center">
                    <span
                      aria-hidden
                      className="mx-auto mb-3.5 flex size-14 items-center justify-center rounded-card border border-border bg-secondary text-muted-foreground"
                    >
                      <FileText className="size-[26px]" />
                    </span>
                    {/* h2, not h3: the page's only other heading is the h1 above,
                        so an h3 skipped a level and axe flagged the outline as
                        broken for anyone navigating by heading. */}
                    <h2 className="text-heading text-foreground">هنوز سندی نیست.</h2>
                    <p className="mx-auto mt-1.5 max-w-[380px] text-caption text-muted-foreground">
                      {search || tab !== "all" || format !== "all"
                        ? "سندی مطابق جستجو یا فیلتر پیدا نشد."
                        : "با «افزودن سند» یا قرار دادن فایل در یکی از پوشه‌ها، پردازش آغاز می‌شود."}
                    </p>
                    {!search && tab === "all" && format === "all" && (
                      <LoadingButton size="sm" className="mt-4" onClick={() => setDialogOpen(true)}>
                        افزودن سند
                      </LoadingButton>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <span className="text-caption text-muted-foreground">
            نمایش {faNum(pageItems.length)} از {faNum(filtered.length)} سند
          </span>
          <div className="flex gap-2">
            <LoadingButton variant="secondary" size="sm" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
              قبلی
            </LoadingButton>
            <LoadingButton variant="secondary" size="sm" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>
              بعدی
            </LoadingButton>
          </div>
        </div>
      </Surface>

      {/* Dialog افزودن پوشه جدید — the PO's exact ask: registering another
          folder must not replace the ones already there. */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="max-w-[560px]">
          <DialogHeader>
            <DialogTitle>افزودن پوشه جدید</DialogTitle>
            <DialogDescription>
              پوشه‌های قبلی حذف نمی‌شوند؛ این پوشه به همان دانش سازمان اضافه می‌شود.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <Input
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              placeholder="C:\\Documents\\HiveOS"
              aria-label="نشانی پوشهٔ جدید"
              dir="ltr"
              data-testid="new-folder-path"
            />
            <div className="mt-3 flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => void chooseLocalFolder()} disabled={!desktop}>
                <FolderOpen aria-hidden />
                انتخاب پوشه از رایانه
              </Button>
              <span className="text-caption text-muted-foreground">
                {desktop
                  ? "می‌توانید پوشه را انتخاب کنید یا نشانی آن را بنویسید."
                  : "در مرورگر، نشانی کامل پوشه را بنویسید."}
              </span>
            </div>
          </DialogBody>
          <DialogFooter>
            <LoadingButton variant="secondary" size="sm" onClick={() => setAddOpen(false)}>
              انصراف
            </LoadingButton>
            <LoadingButton
              size="sm"
              loading={busy}
              disabled={!newPath.trim()}
              onClick={() => void addFolder()}
              data-testid="add-folder-submit"
            >
              افزودن پوشه
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog افزودن سند — الگوی آپلود متعارف ماک‌آپ (بازبینی سوم) */}
      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          // Closing the dialog always drops the picked files: reopening it must
          // never resend the selection that was just confirmed or cancelled.
          if (!open) setPicked([]);
        }}
      >
      
        <DialogContent className="max-w-[640px]">
          <DialogHeader>
            <DialogTitle>افزودن سند</DialogTitle>
            <DialogDescription>
              فایل‌ها را انتخاب یا در کادر زیر رها کنید. فرمت‌های v0.1: PDF، DOCX، TXT، MD، CSV
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {/* A real <button>, not a div with role="button". The div version
                announced itself as a button but kept none of the behaviour: no
                native Enter/Space activation, no disabled state, and the drag
                handlers on the clickable region swallowed text selection.
                Letting the button itself be the drop target keeps one element
                doing one thing. [E4] */}
            <button
              type="button"
              aria-describedby="dropzone-hint"
              data-testid="dropzone"
              onClick={() => fileRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                pickFiles(Array.from(event.dataTransfer.files))
              }}
              className={cn(
                "flex w-full cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed px-6 py-10 text-center transition-colors",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                dragging ? "border-primary bg-accent" : "border-border bg-secondary hover:border-primary/40",
              )}
            >
              <UploadCloud aria-hidden className="mb-2 size-7 text-muted-foreground" />
              <span className="text-caption font-bold text-foreground">فایل‌ها را اینجا رها کنید یا کلیک کنید</span>
              {/* P1-5: the cap is shown up front, from the server's own
                  setting, instead of being discovered after a failed upload. */}
              <span id="dropzone-hint" className="mt-1 text-micro text-muted-foreground" data-testid="dropzone-limit">
                چند فایل در هر بار · حداکثر {faNum(limitMb)} مگابایت برای هر فایل
              </span>
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept={ACCEPTED}
              className="hidden border-border bg-card"
              onChange={(e) => {
                pickFiles(Array.from(e.target.files ?? []));
                // Let the same file be picked again after it was rejected.
                e.target.value = "";
              }}
            />
            {picked.length > 0 && (
              <ul className="mt-3 space-y-2">
                {picked.map((f, i) => (
                  <li key={f.name + i} className="flex items-center gap-3 rounded-control border border-border bg-card px-3 py-2">
                    <FileText aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate text-caption font-semibold text-foreground">{f.name}</span>
                    <span className="font-mono text-micro text-muted-foreground" dir="ltr">
                      {humanSize(f.size)}
                    </span>
                    <button
                      type="button"
                      aria-label={"حذف " + f.name}
                      className="cursor-pointer rounded-xs p-1 text-muted-foreground transition-colors hover:bg-error-bg hover:text-error"
                      onClick={() => setPicked((p) => p.filter((_, idx) => idx !== i))}
                    >
                      <X className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </DialogBody>
          <DialogFooter>
            <LoadingButton variant="secondary" size="sm" onClick={() => setDialogOpen(false)}>
              انصراف
            </LoadingButton>
            <LoadingButton size="sm" onClick={upload} loading={busy} disabled={picked.length === 0} data-testid="upload">
              {picked.length > 0 ? `افزودن به پردازش (${faNum(picked.length)})` : "افزودن به پردازش"}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function CountChip({ value }: { value: number }) {
  return (
    <span className="me-0 rounded-full border border-border bg-secondary px-[7px] text-micro text-muted-foreground">
      {faNum(value)}
    </span>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "info" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-card border border-border bg-card p-[18px] shadow-card",
        tone === "info" && "border-primary/40 bg-accent/60",
        tone === "danger" && "border-error bg-error-bg",
      )}
    >
      <div className="flex items-center gap-1.5 text-caption font-bold text-muted-foreground">
        {tone === "danger" && <CircleAlert aria-hidden className="size-[15px] text-error" />}
        {label}
      </div>
      <div className="mt-2 text-title text-foreground">{value}</div>
    </div>
  );
}
