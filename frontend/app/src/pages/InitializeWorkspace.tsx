import { useEffect, useRef, useState } from "react";
import { api, describeError } from "../api";
import type { WorkspaceInitResult, WorkspaceSettings } from "../api";
import Stepper from "../Stepper";

// Mockup 04: the workspace initializes server-side and returns its 5 settings.
const SETTINGS: { key: keyof WorkspaceSettings; label: string; mono?: boolean }[] = [
  { key: "language", label: "زبان" },
  { key: "timeZone", label: "منطقه زمانی", mono: true },
  { key: "dateFormat", label: "قالب تاریخ", mono: true },
  { key: "numberFormat", label: "قالب اعداد", mono: true },
  { key: "defaultLocale", label: "زبان پیش‌فرض", mono: true },
];

interface Props {
  onDone: (r: { workspaceId: string }) => void;
  onBack: () => void;
}

export default function InitializeWorkspace({ onDone, onBack }: Props) {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState<WorkspaceInitResult | null>(null);
  const [error, setError] = useState("");
  const didInit = useRef(false);

  // The POST is idempotent; the guard avoids a duplicate call from React
  // StrictMode double-invoking effects in dev. `active` is the mounted guard:
  // no setState after unmount.
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    let active = true;
    (async () => {
      try {
        const r = await api.initializeWorkspace();
        if (active) setResult(r);
      } catch (e) {
        if (active) setError(describeError(e, "خطا در راه‌اندازی فضای کار", "سازمان فعال نیست یا فضای کار ناسازگار است."));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <Stepper active={3} />
      <div className="card">
        {loading ? (
          <>
            <div className="loading-head">
              <span className="spinner" />
              <h2 style={{ margin: 0, fontSize: 18 }}>در حال آماده‌سازی فضای کار</h2>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 12 }}>فضای کار شما در حال آماده‌سازی است.</p>
          </>
        ) : error ? (
          <>
            <div className="alerts">
              <div className="alert error">{error}</div>
            </div>
            <div className="actions-row">
              <button type="button" className="btn-secondary" onClick={onBack}>بازگشت</button>
            </div>
          </>
        ) : result ? (
          <>
            <div className="ready">
              <div className="tick">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
              <h2>فضای کار آماده است</h2>
              <p>فضای کار سازمان با موفقیت راه‌اندازی شد.</p>
            </div>

            <div className="kv">
              {SETTINGS.map((s) => (
                <div className="row" key={s.key}>
                  <span className="lbl">{s.label}</span>
                  <span className={`val${s.mono ? " mono" : ""}`}>{result.settings[s.key]}</span>
                </div>
              ))}
            </div>

            <div className="actions-row">
              <button type="button" className="btn-secondary" onClick={onBack}>بازگشت</button>
              <button type="button" className="btn-primary" onClick={() => onDone({ workspaceId: result.workspaceId })}>ادامه</button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
