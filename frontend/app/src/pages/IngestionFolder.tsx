import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import type { DocumentItem, IngestionCounts } from "../api";
import Stepper from "../Stepper";

const FA = "۰۱۲۳۴۵۶۷۸۹";
const toFa = (n: number | string) => String(n).replace(/\d/g, (d) => FA[+d]);

// Mockup 07 status badges + count labels (Persian).
const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  detected: { label: "شناسایی‌شده", cls: "detected" },
  processing: { label: "در حال پردازش", cls: "processing" },
  ready: { label: "آماده", cls: "ready" },
  failed: { label: "ناموفق", cls: "failed" },
};

const COUNT_LABELS: { key: keyof IngestionCounts; label: string }[] = [
  { key: "detected", label: "شناسایی‌شده" },
  { key: "processing", label: "در حال پردازش" },
  { key: "ready", label: "آماده" },
  { key: "failed", label: "ناموفق" },
];

interface Props {
  onDone: (r: { folderPath: string; documents: DocumentItem[] }) => void;
  onBack: () => void;
}

export default function IngestionFolder({ onDone, onBack }: Props) {
  const [folderPath, setFolderPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [configured, setConfigured] = useState(false);
  const [configuredPath, setConfiguredPath] = useState("");
  const [counts, setCounts] = useState<IngestionCounts | null>(null);
  const [docs, setDocs] = useState<DocumentItem[]>([]);

  // Live-refresh the document list every 5s while the folder is configured.
  useEffect(() => {
    if (!configured) return;
    let active = true;
    async function load() {
      try {
        const d = await api.listDocuments();
        if (active) setDocs(d);
      } catch {
        /* keep last known list on transient failure */
      }
    }
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [configured]);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    setError("");
    const p = folderPath.trim();
    if (!p) {
      setError("مسیر پوشه را وارد کنید.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.configureIngestion(p);
      setConfiguredPath(r.folderPath);
      setCounts(r.counts);
      setConfigured(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400) setError("مسیر نادرست");
        else if (err.status === 403) setError("خارج از محدوده مجاز");
        else if (err.status === 409) setError("سازمان فعال نیست");
        else setError(err.message || "خطا در فعال‌سازی پوشه اسناد");
      } else {
        setError((err as Error).message || "خطا در فعال‌سازی پوشه اسناد");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <Stepper active={5} />

      {!configured ? (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>انتخاب مسیر اسناد</h2>
          <p style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.8 }}>
            پوشه‌ای روی رایانه یا سرور که اسناد سازمان در آن قرار دارد را مشخص کنید. فایل‌های PDF، Word و غیره به‌صورت خودکار شناسایی می‌شوند.
          </p>
          <form onSubmit={submit}>
            <div className="field">
              <label>مسیر پوشه <span style={{ color: "var(--err)" }}>*</span></label>
              <input
                className="monospace"
                type="text"
                dir="ltr"
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
                placeholder="C:\Documents\HiveOS"
                autoFocus
              />
              <span className="hint">مسیر مطلق (ساختار کامل) پوشه اسناد را وارد کنید.</span>
            </div>

            {error && <div className="alerts"><div className="alert error">{error}</div></div>}

            <div className="actions-row">
              <button type="button" className="btn-secondary" onClick={onBack}>بازگشت</button>
              <button type="submit" className="btn-primary" disabled={busy}>{busy ? "در حال بررسی…" : "بررسی"}</button>
            </div>
          </form>
        </div>
      ) : (
        <>
          <div className="card">
            <div className="loading-head">
              <svg viewBox="0 0 24 24" fill="none" stroke="var(--brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 22, height: 22 }}>
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
              <h2 style={{ margin: 0, fontSize: 18 }}>اسناد شناسایی‌شده</h2>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 8, lineHeight: 1.8 }}>
              مسیر فعال: <span className="monospace" style={{ fontSize: 12 }}>{configuredPath}</span>
              <br />
              اسناد این پوشه به‌صورت خودکار پردازش می‌شوند و لیست به‌صورت زنده به‌روز می‌شود.
            </p>

            {counts && (
              <div className="counts">
                {COUNT_LABELS.map((c) => (
                  <div className="count-chip" key={c.key}>
                    <div className="n">{toFa(counts[c.key])}</div>
                    <div className="l">{c.label}</div>
                  </div>
                ))}
              </div>
            )}

            {docs.length === 0 ? (
              <div className="loading-head" style={{ marginTop: 12 }}>
                <span className="spinner" />
                <span style={{ fontSize: 13, color: "var(--muted)" }}>در انتظار فایل جدید…</span>
              </div>
            ) : (
              <table className="doc-table">
                <thead>
                  <tr>
                    <th>نام</th>
                    <th>فرمت</th>
                    <th>وضعیت</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((d) => {
                    const b = STATUS_BADGE[d.status] ?? { label: d.status, cls: "detected" };
                    return (
                      <tr key={d.id}>
                        <td>{d.filename}</td>
                        <td><span className="fmt">{d.format}</span></td>
                        <td>
                          <span className={`badge ${b.cls}`}>{b.label}</span>
                          {d.error && <div className="fail-reason">{d.error}</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div className="actions-row" style={{ marginTop: 16 }}>
            <button type="button" className="btn-secondary" onClick={onBack}>بازگشت</button>
            <button type="button" className="btn-primary" onClick={() => onDone({ folderPath: configuredPath, documents: docs })}>ادامه</button>
          </div>
        </>
      )}
    </div>
  );
}
