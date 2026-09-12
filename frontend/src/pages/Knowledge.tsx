import { CircleAlert, FileText, FolderOpen, RefreshCw, Search, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { StatusBadge } from "../components/ui/status-badge";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { DialogBody } from "../components/ui/dialog-body";
import { Input } from "../components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
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
}

interface Job {
  id: string;
  asset_id: string | null;
  status: string;
  stage: string | null;
  error_code: string | null;
}

const STATUS_FA: Record<string, string> = {
  queued: "در صف",
  processing: "در حال پردازش",
  ready: "تکمیل شد",
  failed: "ناموفق",
  deleted: "حذف‌شده",
};

const STATUS_TONE: Record<string, "success" | "error" | "info" | "warning" | "neutral"> = {
  ready: "success",
  failed: "error",
  deleted: "neutral",
  queued: "info",
  processing: "info",
};

// Must stay identical to the server's US-205 table (backend/knowledge/assets.py):
// an extension the picker offers but the server refuses is a broken promise.
const ACCEPTED =
  ".txt,.md,.pdf,.docx,.pptx,.xlsx,.csv,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.webp";

type TabKey = "all" | "ready" | "processing" | "queued" | "failed";
const PAGE_SIZE = 8;

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
      api<{ assets: Asset[] }>("GET", "/knowledge/assets"),
      api<{ jobs: Job[] }>("GET", "/processing/jobs"),
      api<Record<string, unknown>>("GET", "/knowledge"),
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
      await api("POST", "/knowledge/upload", form);
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
      await api("POST", "/knowledge/" + source.id + "/scan");
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
      await api("POST", "/knowledge/assets/" + assetId + "/classify");
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
          <h1 className="text-[19px] font-extrabold text-neutral-900">دانش سازمان</h1>
          <p className="mt-[3px] text-[13px] text-neutral-600">منبع اسناد، وضعیت پردازش و جستجو در اسناد — همه در یک صفحه.</p>
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
                className="flex size-11 shrink-0 items-center justify-center rounded-[12px] bg-amber-soft text-amber"
              >
                <FolderOpen className="size-5" />
              </span>
              <div>
                <div className="text-[15px] font-extrabold text-neutral-900">پوشه اسناد سازمان</div>
                <div className="mt-1 font-mono text-[13px] text-neutral-600" dir="ltr">
                  {source.path}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge tone="success" className="px-3.5 py-[5px] text-xs" dot>
                {source.status === "active" ? "فعال" : source.status}
              </StatusBadge>
              <span className="text-[11px] text-neutral-400">پویش خودکار هر ۳۰ دقیقه</span>
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

      {/* tabs + search (mockup §۱۷) */}
      <Surface className="mb-4 p-4">
        <Tabs value={tab} onValueChange={(v) => { setTab(v as TabKey); setPage(0); }}>
          <TabsList>
            <TabsTrigger value="all">
              همه
              <CountChip value={counts.all} />
            </TabsTrigger>
            <TabsTrigger value="ready">
              تکمیل شد
              <CountChip value={counts.ready} />
            </TabsTrigger>
            <TabsTrigger value="processing">
              در حال پردازش
              <CountChip value={counts.processing} />
            </TabsTrigger>
            <TabsTrigger value="queued">
              در صف
              <CountChip value={counts.queued} />
            </TabsTrigger>
            <TabsTrigger value="failed">
              ناموفق
              <CountChip value={counts.failed} />
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="mt-3 flex flex-wrap gap-3">
          <div className="relative min-w-[220px] flex-1">
            <Search aria-hidden className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
            <Input
              type="search"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="جستجو در اسناد…"
              aria-label="جستجوی اسناد"
              className="ps-9"
            />
          </div>
          <select
            value={format}
            onChange={(e) => { setFormat(e.target.value); setPage(0); }}
            aria-label="فیلتر فرمت"
            className="cursor-pointer rounded-control border border-neutral-200 bg-neutral-0 px-3 py-[11px] text-sm text-neutral-600 focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50"
          >
            <option value="all">همه فرمت‌ها</option>
            {formats.map((f) => (
              <option key={f} value={f}>
                {f.toUpperCase()}
              </option>
            ))}
          </select>
        </div>
      </Surface>

      {/* جدول اسناد (mockup §۸) */}
      <Surface className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-[12px] text-neutral-400">
              <th className="p-3 ps-5 text-start font-bold">نام سند</th>
              <th className="p-3 text-start font-bold">فرمت</th>
              <th className="p-3 text-start font-bold">حجم</th>
              <th className="p-3 text-start font-bold">وضعیت</th>
              <th className="p-3 pe-5 text-start font-bold"></th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((a) => {
              const job = jobByAsset.get(a.id);
              const failedCode = a.status === "failed" ? (job?.error_code ?? "") : "";
              return (
                <tr key={a.id} className="border-b border-neutral-100 last:border-b-0 hover:bg-neutral-50/60">
                  <td className="p-3 ps-5 font-bold text-neutral-900" data-testid="asset-name">
                    {a.name}
                  </td>
                  <td className="p-3">
                    <span className="inline-block rounded-[6px] border border-neutral-200 bg-neutral-50 px-2 py-0.5 font-mono text-[11px] text-neutral-600" dir="ltr">
                      {(a.extension ?? "").toUpperCase()}
                    </span>
                  </td>
                  <td className="p-3 font-mono text-[12px] text-neutral-600" dir="ltr">
                    {humanSize(a.size_bytes)}
                  </td>
                  <td className="p-3" data-testid={"asset-status-" + a.status}>
                    <StatusBadge tone={STATUS_TONE[a.status] ?? "neutral"} dot>
                      {STATUS_FA[a.status] ?? a.status}
                    </StatusBadge>
                    {failedCode && (
                      <div className="mt-1 font-mono text-[10.5px] text-error" dir="ltr">
                        {failedCode}
                      </div>
                    )}
                  </td>
                  <td className="p-3 pe-5 text-end">
                    {a.status === "queued" && (
                      <LoadingButton variant="secondary" size="xs" onClick={() => classify(a.id)} disabled={busy}>
                        دسته‌بندی
                      </LoadingButton>
                    )}
                  </td>
                </tr>
              );
            })}
            {pageItems.length === 0 && (
              <tr>
                <td colSpan={5} className="p-0">
                  <div className="px-5 py-12 text-center">
                    <span
                      aria-hidden
                      className="mx-auto mb-3.5 flex size-14 items-center justify-center rounded-[16px] border border-neutral-200 bg-neutral-50 text-neutral-400"
                    >
                      <FileText className="size-[26px]" />
                    </span>
                    <h3 className="text-[15px] font-extrabold text-neutral-900">هنوز سندی نیست.</h3>
                    <p className="mx-auto mt-1.5 max-w-[380px] text-[13px] text-neutral-600">
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
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <div className="flex items-center justify-between border-t border-neutral-200 px-5 py-3">
          <span className="text-xs text-neutral-400">
            نمایش {faNum(pageItems.length)} از {faNum(filtered.length)} سند
          </span>
          <div className="flex gap-2">
            <LoadingButton variant="secondary" size="xs" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
              قبلی
            </LoadingButton>
            <LoadingButton variant="secondary" size="xs" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>
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
            <div
              role="button"
              tabIndex={0}
              aria-label="انتخاب فایل"
              data-testid="dropzone"
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") fileRef.current?.click(); }}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                setPicked(Array.from(e.dataTransfer.files));
              }}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center rounded-[14px] border-2 border-dashed px-6 py-10 text-center transition-colors",
                dragging ? "border-navy-600 bg-navy-50" : "border-neutral-200 bg-neutral-50 hover:border-navy-200",
              )}
            >
              <UploadCloud aria-hidden className="mb-2 size-7 text-neutral-400" />
              <p className="text-[13px] font-bold text-neutral-900">فایل‌ها را اینجا رها کنید یا کلیک کنید</p>
              <p className="mt-1 text-[11.5px] text-neutral-400">چند فایل در هر بار</p>
            </div>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => setPicked(Array.from(e.target.files ?? []))}
            />
            {picked.length > 0 && (
              <ul className="mt-3 space-y-2">
                {picked.map((f, i) => (
                  <li key={f.name + i} className="flex items-center gap-3 rounded-[10px] border border-neutral-200 bg-neutral-0 px-3 py-2">
                    <FileText aria-hidden className="size-4 shrink-0 text-neutral-400" />
                    <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-neutral-900">{f.name}</span>
                    <span className="font-mono text-[11px] text-neutral-400" dir="ltr">
                      {humanSize(f.size)}
                    </span>
                    <button
                      type="button"
                      aria-label={"حذف " + f.name}
                      className="cursor-pointer rounded-[7px] p-1 text-neutral-400 transition-colors hover:bg-error-bg hover:text-error"
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
    <span className="me-0 rounded-full border border-neutral-200 bg-neutral-50 px-[7px] text-[10.5px] text-neutral-600">
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
        "rounded-[16px] border border-neutral-200 bg-neutral-0 p-[18px] shadow-card",
        tone === "info" && "border-navy-200 bg-navy-50/60",
        tone === "danger" && "border-error bg-error-bg",
      )}
    >
      <div className="flex items-center gap-1.5 text-xs font-bold text-neutral-600">
        {tone === "danger" && <CircleAlert aria-hidden className="size-[15px] text-error" />}
        {label}
      </div>
      <div className="mt-2 text-2xl font-extrabold tracking-[-0.5px] text-neutral-900">{value}</div>
    </div>
  );
}
