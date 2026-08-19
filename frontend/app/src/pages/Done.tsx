import { useEffect, useRef, useState } from "react";
import { api, ApiError, describeError } from "../api";
import type { DocumentItem } from "../api";
import Stepper from "../Stepper";

const FA = "۰۱۲۳۴۵۶۷۸۹";
const toFa = (n: number | string) => String(n).replace(/\d/g, (d) => FA[+d]);

// US-008 missingSteps -> Persian labels + wizard step index to jump back to.
const STEP_LABELS: Record<string, string> = {
  "register-organization": "ساخت سازمان",
  "owner-account": "مدیر",
  "verify-owner": "تأیید کد",
  workspace: "فضای کار",
  brain: "هوش سازمان",
  "ingestion-folder": "اسناد",
};
const STEP_INDEX: Record<string, number> = {
  "register-organization": 0,
  "owner-account": 1,
  "verify-owner": 2,
  workspace: 3,
  brain: 4,
  "ingestion-folder": 5,
};

interface Props {
  orgName?: string;
  documents?: DocumentItem[];
  onJump: (step: number) => void;
}

export default function Done({ orgName, documents, onJump }: Props) {
  const [loading, setLoading] = useState(true);
  const [completed, setCompleted] = useState(false);
  const [missing, setMissing] = useState<string[]>([]);
  const [error, setError] = useState("");
  const didInit = useRef(false);

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    let active = true;
    (async () => {
      try {
        const status = await api.getOnboardingStatus();
        if (!active) return;
        if (status.missingSteps && status.missingSteps.length > 0) {
          setMissing(status.missingSteps);
          return;
        }
        const r = await api.completeOnboarding();
        if (!active) return;
        if (r.onboardingStatus === "completed") setCompleted(true);
        else setError("راه‌اندازی هنوز کامل نشده است. کمی بعد دوباره تلاش کنید.");
      } catch (e) {
        if (!active) return;
        if (e instanceof ApiError && e.status === 409) {
          const d = e.details as { missingSteps?: string[] } | undefined;
          if (d?.missingSteps && d.missingSteps.length > 0) setMissing(d.missingSteps);
          else setError(describeError(e, "خطا در تکمیل راه‌اندازی", "مراحلی از راه‌اندازی ناتمام مانده است."));
        } else {
          setError(describeError(e, "خطا در تکمیل راه‌اندازی"));
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const readyDocs = documents?.filter((d) => d.status === "ready").length ?? 0;
  const summary = [
    { lbl: "ثبت سازمان", val: orgName ?? "ثبت شد" },
    { lbl: "حساب مدیر", val: "تأیید شد" },
    { lbl: "فضای کار", val: "آماده" },
    { lbl: "هوش سازمان", val: "آماده" },
    { lbl: "اسناد", val: `${toFa(readyDocs)} فایل آماده` },
  ];

  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <Stepper active={6} />
      <div className="card">
        {loading ? (
          <div className="loading-head">
            <span className="spinner" />
            <h2 style={{ margin: 0, fontSize: 18 }}>در حال تکمیل راه‌اندازی</h2>
          </div>
        ) : error ? (
          <>
            <div className="alerts">
              <div className="alert error">{error}</div>
            </div>
            <div className="actions-row">
              <button type="button" className="btn-secondary" onClick={() => onJump(5)}>بازگشت</button>
            </div>
          </>
        ) : completed ? (
          <>
            <div style={{ textAlign: "center", marginBottom: 24 }}>
              <div style={{ width: 76, height: 76, borderRadius: "50%", background: "var(--ok)", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 16, boxShadow: "0 8px 24px rgba(22,163,74,.3)" }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ width: 38, height: 38 }}>
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
              <div>
                <span className="badge ready" style={{ marginBottom: 12 }}>راه‌اندازی کامل شد</span>
                <h1 style={{ fontSize: 22, fontWeight: 800, margin: "12px 0 0" }}>سازمان شما آماده است!</h1>
                <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 8, lineHeight: 1.9 }}>اکنون می‌توانید درباره اسناد و کارهای سازمان با هوش سازمان گفتگو کنید.</p>
              </div>
            </div>

            <div className="summary">
              <div className="summary-title">مراحل انجام‌شده</div>
              {summary.map((s) => (
                <div className="row" key={s.lbl}>
                  <span className="check">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </span>
                  <span className="lbl">{s.lbl}</span>
                  <span className="val">{s.val}</span>
                </div>
              ))}
            </div>

            <button className="btn-primary" disabled style={{ width: "100%" }}>شروع گفتگو با هوش سازمان</button>
            <p style={{ fontSize: 12, color: "var(--muted)", textAlign: "center", marginTop: 8 }}>
              راه‌اندازی گفتگو در فاز بعد
            </p>

            <div className="quickstart">
              <h3>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                شروع سریع
              </h3>
              <ul>
                <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>سوال خود را درباره سازمان یا اسناد بپرسید.</li>
                <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>اسناد تازه را در فولدر مشخص‌شده بگذارید تا خودکار پردازش شوند.</li>
                <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>برای انجام تغییرات به تنظیمات مراجعه کنید.</li>
              </ul>
            </div>
          </>
        ) : missing.length > 0 ? (
          <>
            <h2 style={{ marginTop: 0 }}>مراحلی ناتمام مانده‌اند</h2>
            <p style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.8 }}>
              برای تکمیل راه‌اندازی، مراحل زیر باید انجام شوند:
            </p>
            <div className="kv">
              {missing.map((m) => (
                <div className="row" key={m}>
                  <span className="lbl">{STEP_LABELS[m] ?? m}</span>
                  <button
                    type="button"
                    className="btn-ghost"
                    style={{ padding: "6px 14px", fontSize: 13 }}
                    onClick={() => onJump(STEP_INDEX[m] ?? 0)}
                  >
                    رفتن به مرحله
                  </button>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="loading-head">
            <span className="spinner" />
            <span style={{ fontSize: 13, color: "var(--muted)" }}>در حال تکمیل راه‌اندازی…</span>
          </div>
        )}
      </div>
    </div>
  );
}
