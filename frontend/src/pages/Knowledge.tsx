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

type TabKey = "all" | "ready" | "processing" | "queued" | "failed";
const PAGE_SIZE = 8;

/**
 * What a document is doing inside the pipeline (H2).
 *
 * The document table used to show only a coarse status, so a file waiting its
 * turn and one that had already been read but not split into knowledge units
 * looked identical — an operator could not tell whether a stuck queue was
 * moving. The API reports the stage it actually reached, and this renders it.
 *
 * Deliberately not a percentage: the server knows how far it got, not how much
 * remains, and a progress bar invented from an unknown denominator is a lie that
 * looks like information.
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
  const fileRef = useRef<HTMLInputElement>(null);

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

  async function upload() {
    if (picked.length === 0) {
      setError("ابتدا فایل را انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const form = new FormData();
      for (const f of picked) form.append("files", f);
      await api("POST", "/knowledge-assets/upload", form);
      setNotice("فایل‌ها در صف پردازش قرار گرفتند.");
      setPicked([]);
      setDialogOpen(false);
      await reload();
    } catch (exc) {
      // D6: keep the server's reason (size cap, format, quota) instead of a
      // generic message that hides it.
      setError(exc instanceof ApiError ? exc.message : "آپلود ناموفق بود.");
    } finally {
      setBusy(false);
    }
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
    try {
      if (folder.source_type === "client_folder") {
        if (!desktop) {
          setError("این پوشه روی رایانهٔ شماست؛ همگام‌سازی آن از برنامهٔ ویندوزی HiveOS انجام می‌شود.");
          return;
        }
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
        await api("POST", "/knowledge-sources/" + folder.id + "/scan");
        setNotice("پویش دستی اجرا شد.");
      }
      await reload();
    } catch (e) {
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

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: assets.length, ready: 0, processing: 0, queued: 0, failed: 0 };
    for (const a of assets) if (c[a.status] !== undefined) c[a.status] += 1;
    return c;
  }, [assets]);

  const filtered = useMemo(() => {
    const q = norm(search);
    return assets.filter((a) => {
      if (tab !== "all" && a.status !== tab) return false;
      if (format !== "all" && (a.extension ?? "").replace(".", "").toLowerCase() !== format) return false;
      if (q && !norm(a.name).includes(q)) return false;
      return true;
    });
  }, [assets, tab, search, format]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const formats = useMemo(
    () => Array.from(new Set(assets.map((a) => (a.extension ?? "").replace(".", "").toLowerCase()).filter(Boolean))),
    [assets],
  );
  const readyCount = counts.ready;
  const activeCount = counts.processing + counts.queued;

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
              </div>
            </div>
          </div>
          <LoadingButton size="sm" className="mt-4" onClick={() => setAddOpen(true)}>
            <FolderPlus aria-hidden />
            افزودن پوشه جدید
          </LoadingButton>
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
        <StatCard label="کل اسناد" value={faNum(assets.length)} />
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
              const failedReason =
                a.status === "failed" ? persianError(jobFailureCode(job?.error_detail)) : "";
              return (
                <TableRow key={a.id} className="border-border last:border-0">
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
                    <DomainStatus domain="asset" value={a.status} dot />
                    {failedReason && (
                      <div className="mt-1 text-micro leading-relaxed text-error">{failedReason}</div>
                    )}
                  </TableCell>
                  {/* H2: what the document is actually doing. A file that has
                      been extracted but not chunked reads differently from one that
                      has not been touched, and the operator can tell whether a
                      stuck queue is moving. Stage names, never a made-up
                      percentage. */}
                  <TableCell className="p-3" data-testid={"asset-progress-" + a.id}>
                    <AssetProgress asset={a} />
                  </TableCell>
                  <TableCell className="p-3 pe-5 text-end">
                    {a.status === "ready" && (
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
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
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
