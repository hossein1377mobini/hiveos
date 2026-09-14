import { CircleAlert, FileText, FolderOpen, RefreshCw, Search, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { persianError } from "../api/errors";
import { DomainStatus } from "../components/ui/domain-status";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { DialogBody } from "../components/ui/dialog-body";
import { Input } from "../components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { RetryNotice } from "../components/ui/retry";
import { cn } from "../lib/utils";
import { faNum, humanSize, norm } from "../utils/format";
import { Surface } from "../components/ui/surface";

// 02-knowledge/01-knowledge-home.html at mockup fidelity: page-head with
// پویش اکنون/افزودن سند, source card (folder icon, active badge, auto-scan
// note), stat cards, status tabs with count chips, live search + format
// filter, document table with format/size/status/actions, table-foot paging,
// add-document dialog with dropzone, empty state. Business logic unchanged
// (GET assets/jobs, POST scan, multipart upload US-201 Am2, classify).
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

// Must stay identical to the server's US-205 table (backend/knowledge/assets.py):
// an extension the picker offers but the server refuses is a broken promise.
const ACCEPTED =
  ".txt,.md,.pdf,.docx,.pptx,.xlsx,.csv,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.webp";

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
  const [source, setSource] = useState<{ id: string; path: string; status: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<TabKey>("all");
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState("all");
  const [page, setPage] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [picked, setPicked] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [a, j, s] = await Promise.all([
      // The asset router moved off "/knowledge" to "/knowledge-assets" when the
      // source router was split out, and this page was left calling the old
      // prefix - so every one of these four calls 404'd. The unit suite stubbed
      // the same wrong string, which is exactly why it stayed green.
      api<{ assets: Asset[] }>("GET", "/knowledge-assets"),
      api<{ jobs: Job[] }>("GET", "/processing/jobs"),
      api<Record<string, unknown>>("GET", "/knowledge-sources"),
    ]);
    setAssets(a.assets ?? []);
    setJobs(j.jobs ?? []);
    setSource(
      s && "id" in s ? { id: String(s.id), path: String(s.path ?? ""), status: String(s.status ?? "") } : null,
    );
    setLoadError(null);
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
  }, [refresh]);

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

  async function scanNow() {
    if (!source) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api("POST", "/knowledge-sources/" + source.id + "/scan");
      setNotice("پویش دستی اجرا شد.");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "پویش ناموفق بود.");
    } finally {
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
          <h1 className="text-heading font-bold text-foreground">دانش سازمان</h1>
          <p className="mt-[3px] text-caption text-muted-foreground">منبع اسناد، وضعیت پردازش و جستجو در اسناد — همه در یک صفحه.</p>
        </div>
        <div className="ms-auto flex items-center gap-2">
          {source && (
            <LoadingButton variant="secondary" size="sm" onClick={scanNow} loading={busy}>
              <RefreshCw aria-hidden />
              پویش اکنون
            </LoadingButton>
          )}
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

      {/* کارت منبع پوشه (mockup) */}
      {source && (
        <Surface className="mb-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span
                aria-hidden
                className="flex size-11 shrink-0 items-center justify-center rounded-control bg-amber-soft text-amber"
              >
                <FolderOpen className="size-5" />
              </span>
              <div>
                <div className="text-body font-bold text-foreground">پوشه اسناد سازمان</div>
                <div className="mt-1 font-mono text-caption text-muted-foreground" dir="ltr">
                  {source.path}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {/* The watch state is a health signal, not a knowledge status:
                  "active" here means the scheduled scan is running. */}
              {/* The source status is "active" | "disabled" - the watch state,
                  not a health probe. Rendering it through the health registry
                  fell through to the raw value, so the badge read "active" in
                  English. It has its own registry now. */}
              <DomainStatus domain="source" value={source.status} dot />
              <span className="text-micro text-muted-foreground">پویش خودکار هر ۳۰ دقیقه</span>
            </div>
          </div>
          <div className="mt-4">
            <Banner tone="info">
              فایل‌های تازه‌ای که در این پوشه قرار می‌دهید، در پویش بعدی (حداکثر ۳۰ دقیقه) شناسایی و پردازش می‌شوند.
              برای پردازش فوری از «پویش اکنون» استفاده کنید یا سند را مستقیم از رایانه اضافه کنید.
            </Banner>
          </div>
        </Surface>
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
                "inline-flex cursor-pointer items-center gap-1.5 rounded-control border px-2.5 py-1 text-sm font-semibold transition-colors",
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
              className="h-[42px] w-[150px] rounded-control border-border bg-card text-sm text-muted-foreground"
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
                    <h2 className="text-body font-bold text-foreground">هنوز سندی نیست.</h2>
                    <p className="mx-auto mt-1.5 max-w-[380px] text-caption text-muted-foreground">
                      {search || tab !== "all" || format !== "all"
                        ? "سندی مطابق جستجو یا فیلتر پیدا نشد."
                        : "با «افزودن سند» یا قرار دادن فایل در پوشه اسناد، پردازش آغاز می‌شود."}
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
          <span className="text-xs text-muted-foreground">
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
                setPicked(Array.from(event.dataTransfer.files))
              }}
              className={cn(
                "flex w-full cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed px-6 py-10 text-center transition-colors",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                dragging ? "border-primary bg-accent" : "border-border bg-secondary hover:border-primary/40",
              )}
            >
              <UploadCloud aria-hidden className="mb-2 size-7 text-muted-foreground" />
              <span className="text-caption font-bold text-foreground">فایل‌ها را اینجا رها کنید یا کلیک کنید</span>
              <span id="dropzone-hint" className="mt-1 text-micro text-muted-foreground">
                چند فایل در هر بار · حداکثر ۵۰ مگابایت برای هر فایل
              </span>
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept={ACCEPTED}
              className="hidden border-border bg-card"
              onChange={(e) => setPicked(Array.from(e.target.files ?? []))}
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
      <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground">
        {tone === "danger" && <CircleAlert aria-hidden className="size-[15px] text-error" />}
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold tracking-[-0.5px] text-foreground">{value}</div>
    </div>
  );
}