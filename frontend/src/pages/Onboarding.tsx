import { useEffect, useState } from "react";
import { api, clearToken } from "../api/client";

// 04/05/06/07 mockups — the automatic steps run in order; the ingestion folder
// is the only user input (US-007). «شروع گفتگو» ends onboarding (US-008 later).
interface Status {
  organization_status: string;
  workspace_ready: boolean;
  brain_ready: boolean;
  knowledge_source: { id: string; path: string; status: string } | null;
  next_step: string;
}

export default function Onboarding({ onStatus }: { onStatus: (status: Status) => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [checked, setChecked] = useState<string | null>(null);
  const [fileCount, setFileCount] = useState<number | null>(null);

  async function refresh(): Promise<Status> {
    const next = await api<Status>("GET", "/auth/onboarding-status");
    setStatus(next);
    onStatus(next);
    return next;
  }

  useEffect(() => {
    (async () => {
      try {
        const next = await refresh();
        // 04/05: the automatic steps — run once, silently, in order.
        if (!next.workspace_ready) await api("POST", "/workspaces/initialize");
        const now = await refresh();
        if (!now.brain_ready) await api("POST", "/brain/initialize");
        await refresh();
        setBusy(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : "خطا");
        setBusy(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function checkFolder() {
    setBusy(true);
    setError(null);
    try {
      // US-007 FR-002: «بررسی» = validate before registration (register is
      // idempotent for the single v0.1 folder; a failed register leaves nothing).
      const data = await api<{ id: string; file_state: string | number }>(
        "POST",
        "/knowledge-sources",
        { path: folder },
      );
      setChecked(data.id);
      await refresh();
      if (typeof data.file_state === "number") setFileCount(data.file_state);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function scanNow() {
    if (!status?.knowledge_source) return;
    setBusy(true);
    try {
      const data = await api<{ file_state: string | number }>(
        "POST",
        `/knowledge-sources/${status.knowledge_source.id}/scan`,
      );
      if (typeof data.file_state === "number") setFileCount(data.file_state);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  if (busy && !status) {
    return <Card><p className="text-sm text-neutral-600">در حال راه‌اندازی فضای کاری و هوش سازمان…</p></Card>;
  }

  if (status?.next_step === "expired") {
    return (
      <Card>
        <h1 className="text-lg font-bold">ثبت‌نام این سازمان منقضی شد</h1>
        <p className="mt-2 text-sm text-neutral-600">سازمان در بازه‌ی مجاز تکمیل نشد. از ابتدا ثبت‌نام کنید.</p>
        <button onClick={() => { clearToken(); location.reload(); }} className="mt-4 rounded-control border border-neutral-200 px-4 py-2 text-sm">
          بازگشت به ورود
        </button>
      </Card>
    );
  }

  return (
    <Card>
      <h1 className="text-lg font-bold">تعیین فولدر اسناد</h1>
      <p className="mt-1 text-sm text-neutral-600">
        مسیر یک فولدر روی همین سرور را وارد کنید؛ اسناد آن به دانش سازمان اضافه می‌شود.
      </p>
      <div className="mt-4 flex gap-2">
        <input
          dir="ltr"
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          placeholder="C:/HiveOS/Documents"
          className="flex-1 rounded-control border border-neutral-200 px-3 py-2 text-left"
        />
        <button onClick={checkFolder} disabled={busy || !folder} className="rounded-control bg-navy-600 px-4 py-2 font-bold text-white disabled:opacity-60">
          بررسی
        </button>
      </div>
      {error && <div className="mt-3 rounded-control bg-error-bg p-3 text-sm text-error">{error}</div>}
      {checked && (
        <div className="mt-4 rounded-control bg-success-bg p-3 text-sm text-success">
          {fileCount !== null && fileCount > 0
            ? `پوشه ثبت شد؛ ${fileCount} فایل شناسایی شد و برای پردازش به صف رفت.`
            : "پوشه ثبت شد؛ در انتظار فایل است. می‌توانید همین حالا گفتگو را شروع کنید."}
        </div>
      )}
      {checked && (
        <div className="mt-4 flex gap-2">
          <button onClick={scanNow} disabled={busy} className="rounded-control border border-neutral-200 px-4 py-2 text-sm disabled:opacity-60">
            پویش اکنون
          </button>
          <button onClick={() => onStatus(status!)} className="flex-1 rounded-control bg-navy-600 py-2 font-bold text-white">
            شروع گفتگو
          </button>
        </div>
      )}
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <section className="mx-auto w-full max-w-md rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
      {children}
    </section>
  );
}
