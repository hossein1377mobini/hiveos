import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// 02-knowledge mockups (01 home + 02 detail): source card with scan state,
// document table (queued/ready/failed + needs_review badge), upload dialog,
// scan-now. Upload uses multipart POST /knowledge/upload (US-201 Am2).
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

function badgeTone(status: string) {
  if (status === "ready") return "bg-green-50 text-green-800";
  if (status === "failed") return "bg-red-50 text-red-800";
  if (status === "deleted") return "bg-neutral-100 text-neutral-600";
  return "bg-amber-50 text-amber-800"; // queued/processing
}

export default function Knowledge() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [source, setSource] = useState<{ id: string; path: string; status: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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
  }, []);

  useEffect(() => {
    reload().catch(() => setError("دریافت وضعیت دانش ناموفق بود."));
  }, [reload]);

  async function upload() {
    const files = fileRef.current?.files;
    if (!files || files.length === 0) {
      setError("ابتدا فایل را انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const form = new FormData();
      for (const f of Array.from(files)) form.append("files", f);
      const token = localStorage.getItem("hiveos.session");
      const response = await fetch("/api/v1/knowledge/upload", {
        method: "POST",
        headers: { Authorization: "Bearer " + token },
        body: form,
      });
      if (!response.ok) throw new Error("upload failed");
      setNotice("فایل‌ها در صف پردازش قرار گرفتند.");
      if (fileRef.current) fileRef.current.value = "";
      await reload();
    } catch {
      setError("آپلود ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  async function scanNow() {
    if (!source) return;
    setBusy(true);
    try {
      await api("POST", "/knowledge/" + source.id + "/scan");
      setNotice("پویش دستی اجرا شد.");
      await reload();
    } catch {
      setError("پویش ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  async function classify(assetId: string) {
    setBusy(true);
    try {
      await api("POST", "/knowledge/assets/" + assetId + "/classify");
      setNotice("دسته‌بندی سند اجرا شد.");
      await reload();
    } catch {
      setError("دسته‌بندی ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  const jobByAsset = new Map<string, Job>();
  for (const j of jobs) if (j.asset_id) jobByAsset.set(j.asset_id, j);

  return (
    <section className="mx-auto max-w-4xl space-y-4" aria-label="دانش سازمان">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">دانش سازمان</h1>
        {source && (
          <button
            type="button"
            onClick={scanNow}
            disabled={busy}
            className="rounded-control border border-neutral-200 px-3 py-2 text-sm"
          >
            پویش اکنون
          </button>
        )}
      </div>

      {source && (
        <div className="rounded-card border border-neutral-200 bg-neutral-0 p-4 text-sm shadow-card">
          <p className="font-bold">منبع پوشه</p>
          <p dir="ltr" className="mt-1 text-xs text-neutral-500">
            {source.path}
          </p>
          <span className={"mt-2 inline-block rounded-control px-2 py-1 text-xs " + badgeTone(source.status === "active" ? "ready" : "queued")}>
            {source.status === "active" ? "فعال" : source.status}
          </span>
        </div>
      )}

      {notice && <p className="rounded-card bg-green-50 p-3 text-sm text-green-800">{notice}</p>}
      {error && <p role="alert" className="rounded-card bg-red-50 p-3 text-sm text-red-800">{error}</p>}

      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-4 shadow-card" aria-label="افزودن سند">
        <h2 className="text-sm font-bold">افزودن سند</h2>
        <div className="mt-2 flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.csv"
            aria-label="انتخاب فایل"
            className="text-sm"
          />
          <button
            type="button"
            onClick={upload}
            disabled={busy}
            data-testid="upload"
            className="rounded-control bg-navy-600 px-4 py-2 text-sm font-bold text-white"
          >
            آپلود
          </button>
        </div>
        <p className="mt-1 text-xs text-neutral-500">
          فرمت‌های v0.1: PDF، DOCX، TXT، MD، CSV
        </p>
      </div>

      <div className="overflow-x-auto rounded-card border border-neutral-200 bg-neutral-0 shadow-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-neutral-600">
              <th className="p-3 text-start">نام سند</th>
              <th className="p-3 text-start">فرمت</th>
              <th className="p-3 text-start">وضعیت</th>
              <th className="p-3 text-start"></th>
            </tr>
          </thead>
          <tbody>
            {assets.map((a) => {
              const job = jobByAsset.get(a.id);
              return (
                <tr key={a.id} className="border-b border-neutral-100">
                  <td className="p-3 font-bold" data-testid="asset-name">
                    {a.name}
                  </td>
                  <td className="p-3" dir="ltr">
                    {a.extension}
                  </td>
                  <td className="p-3">
                    <span
                      className={"inline-block rounded-control px-2 py-1 text-xs " + badgeTone(a.status)}
                      data-testid={"asset-status-" + a.status}
                    >
                      {STATUS_FA[a.status] ?? a.status}
                    </span>
                    {job?.error_code && (
                      <span className="ms-2 text-xs text-red-700" dir="ltr">
                        {job.error_code}
                      </span>
                    )}
                  </td>
                  <td className="p-3">
                    {a.status === "queued" && (
                      <button
                        type="button"
                        onClick={() => classify(a.id)}
                        disabled={busy}
                        className="rounded-control border border-neutral-200 px-2 py-1 text-xs"
                      >
                        دسته‌بندی
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {assets.length === 0 && (
              <tr>
                <td colSpan={4} className="p-6 text-center text-neutral-500">
                  هنوز سندی نیست.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
