import { FolderOpen, FolderSearch, House, Server, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, clearToken } from "../api/client";
import { AuthBrand, Field, PanelHead, StepsList, Stepper } from "../components/auth/parts";
import { Banner } from "../components/ui/banner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { faNum } from "../utils/format";

// 04/05/06/07 mockups — the automatic steps (workspace, brain) run in order
// behind the stepper, then the ingestion folder card (06) is the only user
// input (US-007); «شروع گفتگو» ends onboarding (US-008 later). 07-complete is
// skipped because the server flips next_step to "chat" and App navigates
// straight to the chat area.
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

  const stage = !status ? "workspace" : !status.workspace_ready ? "workspace" : !status.brain_ready ? "brain" : "folder";

  return (
    <section aria-label="راه‌اندازی سازمان">
      <AuthBrand title="راه‌اندازی سازمان" subtitle="چند گام کوتاه تا گفتگو با هوش سازمان." />
      <Stepper current={stage === "workspace" ? 4 : stage === "brain" ? 5 : 6} />

      {status?.next_step === "expired" && (
        <div className="rounded-card border border-neutral-200 bg-neutral-0 p-7 shadow-card">
          <PanelHead icon={FolderOpen} tone="error" title="ثبت‌نام این سازمان منقضی شد" />
          <p className="text-[13px] text-neutral-600">سازمان در بازه‌ی مجاز تکمیل نشد. از ابتدا ثبت‌نام کنید.</p>
          <Button variant="secondary" className="mt-4" onClick={() => { clearToken(); location.reload(); }}>
            بازگشت به ورود
          </Button>
        </div>
      )}

      {status?.next_step !== "expired" && stage === "workspace" && (
        <div className="rounded-card border border-neutral-200 bg-neutral-0 p-7 shadow-card">
          <PanelHead icon={Server} tone="violet" title="در حال آماده‌سازی فضای کار" hint="گام ۴ از ۶" />
          <p className="mb-2 text-[13px] text-neutral-600">این مرحله خودکار انجام می‌شود؛ چند لحظه صبر کنید.</p>
          <StepsList
            items={[
              { name: "ایجاد فضای کار", state: busy ? "active" : "done", marker: "۱" },
              { name: "اعمال تنظیمات اولیه", state: busy ? "active" : "done", marker: "۲" },
              { name: "آماده‌سازی فضای ذخیره‌سازی", state: busy ? "active" : "done", marker: "۳" },
            ]}
          />
          {error && (
            <div className="mt-4">
              <Banner tone="error" title="راه‌اندازی فضای کار ناموفق بود.">{error}</Banner>
            </div>
          )}
        </div>
      )}

      {status?.next_step !== "expired" && stage === "brain" && (
        <div className="rounded-card border border-neutral-200 bg-neutral-0 p-7 shadow-card">
          <PanelHead icon={Sparkles} tone="teal" title="در حال ساخت هوش سازمان" hint="گام ۵ از ۶" />
          <p className="mb-2 text-[13px] text-neutral-600">
            مخزن دانش ساخته می‌شود؛ تا پایان این مرحله، توصیف کسب‌وکار شما پاسخ‌گوی اولیه است.
          </p>
          <StepsList
            items={[
              { name: "ایجاد مخزن دانش", state: busy ? "active" : "done", marker: "۱" },
              { name: "در حال پیکربندی", state: busy ? "active" : "done", marker: "۲" },
              { name: "به‌کارگیری مدل", state: busy ? "active" : "done", marker: "۳" },
            ]}
          />
          {error && (
            <div className="mt-4">
              <Banner tone="error" title="ساخت هوش سازمان ناموفق بود.">{error}</Banner>
            </div>
          )}
        </div>
      )}

      {status?.next_step !== "expired" && stage === "folder" && (
        <div className="rounded-card border border-neutral-200 bg-neutral-0 p-7 shadow-card">
          <PanelHead icon={FolderSearch} tone="amber" title="تعیین پوشه اسناد" hint="گام ۶ از ۶" />
          <p className="mb-4 text-[13px] text-neutral-600">
            مسیر یک پوشه روی همین سرور را وارد کنید؛ اسناد آن به دانش سازمان اضافه می‌شود.
          </p>

          {/* الگوی folder-pick ماک‌آپ (بازبینی پنجم): ردیف پوشه + مسیر mono */}
          <Field label="مسیر پوشه اسناد" required hint="مثلاً C:\HiveOS\Documents یا /srv/hive-docs">
            <div className="flex items-center gap-3 rounded-[12px] border border-neutral-200 bg-neutral-0 p-2.5 ps-3">
              <span
                aria-hidden
                className="flex size-10 shrink-0 items-center justify-center rounded-[11px] bg-amber-soft text-amber"
              >
                <FolderOpen className="size-5" />
              </span>
              <Input
                dir="ltr"
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
                placeholder="C:/HiveOS/Documents"
                className="flex-1 border-0 font-mono text-[13px] shadow-none focus:ring-0"
                aria-label="مسیر پوشه اسناد"
              />
              <Button size="sm" onClick={checkFolder} loading={busy} disabled={!folder.trim()}>
                بررسی و ثبت
              </Button>
            </div>
          </Field>

          <Banner tone="info">
            فایل‌های این پوشه در پویش بعدی (حداکثر هر ۳۰ دقیقه) شناسایی و پردازش می‌شوند. برای پردازش فوری از
            «پویش اکنون» استفاده کنید.
          </Banner>

          {error && (
            <div className="mt-4">
              <Banner tone="error" title="ثبت پوشه ناموفق بود.">{error}</Banner>
            </div>
          )}
          {checked && (
            <div className="mt-4">
              <Banner tone="success" title={`پوشه ثبت شد${fileCount !== null && fileCount > 0 ? ` — ${faNum(fileCount)} فایل شناسایی شد و برای پردازش به صف رفت.` : "؛ در انتظار فایل است."}`}>
                می‌توانید همین حالا گفتگو را شروع کنید.
              </Banner>
            </div>
          )}

          {checked && (
            <div className="mt-5 flex gap-2.5">
              <Button variant="secondary" onClick={scanNow} loading={busy}>
                پویش اکنون
              </Button>
              <Button className="flex-1" onClick={() => { if (status) onStatus(status); }}>
                <House aria-hidden className="rtl:-scale-x-100" />
                شروع گفتگو
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}