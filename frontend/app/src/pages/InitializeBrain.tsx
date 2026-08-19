import { useEffect, useRef, useState } from "react";
import { api, describeError } from "../api";
import type { BrainInitResult } from "../api";
import Stepper from "../Stepper";

// Mockup 05: the brain returns its IDs + RAG config after initialization.
const FIELDS: { key: keyof BrainInitResult | "rag.embeddingProvider" | "rag.defaultLanguage"; label: string; mono?: boolean }[] = [
  { key: "brainId", label: "شناسه هوش سازمان", mono: true },
  { key: "knowledgeRepositoryId", label: "شناسه مخزن دانش", mono: true },
  { key: "vectorIndexId", label: "شناسه نمای برداری", mono: true },
  { key: "rag.embeddingProvider", label: "ارائه‌دهنده بردارسازی" },
  { key: "rag.defaultLanguage", label: "زبان پیش‌فرض" },
];

function fieldValue(r: BrainInitResult, key: string): string {
  if (key === "rag.embeddingProvider") return r.rag.embeddingProvider;
  if (key === "rag.defaultLanguage") return r.rag.defaultLanguage;
  return String((r as unknown as Record<string, unknown>)[key]);
}

interface Props {
  onDone: (r: { brainId: string }) => void;
  onBack: () => void;
}

export default function InitializeBrain({ onDone, onBack }: Props) {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState<BrainInitResult | null>(null);
  const [error, setError] = useState("");
  const didInit = useRef(false);

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    let active = true;
    (async () => {
      try {
        const r = await api.initializeBrain();
        if (active) setResult(r);
      } catch (e) {
        if (active) setError(describeError(e, "خطا در راه‌اندازی هوش سازمان", "فضای کار هنوز آماده نیست."));
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
      <Stepper active={4} />
      <div className="card">
        {loading ? (
          <>
            <div className="loading-head">
              <span className="spinner" />
              <h2 style={{ margin: 0, fontSize: 18 }}>در حال راه‌اندازی هوش سازمان</h2>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 12 }}>هوش سازمان شما در حال آماده‌سازی است.</p>
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
              <h2>هوش سازمان آماده است</h2>
              <p>هوش سازمان راه‌اندازی شد و آماده دریافت اسناد است.</p>
            </div>

            <div className="kv">
              {FIELDS.map((f) => (
                <div className="row" key={f.key}>
                  <span className="lbl">{f.label}</span>
                  <span className={`val${f.mono ? " mono" : ""}`}>{fieldValue(result, f.key)}</span>
                </div>
              ))}
            </div>

            <div className="actions-row">
              <button type="button" className="btn-secondary" onClick={onBack}>بازگشت</button>
              <button type="button" className="btn-primary" onClick={() => onDone({ brainId: result.brainId })}>ادامه</button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
