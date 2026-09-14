import { FolderOpen, FolderSearch, House, RefreshCw, Server, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, clearToken } from "../api/client";
import { AuthBrand, Field, PanelHead, StepsList, Stepper } from "../components/auth/parts";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { Input } from "../components/ui/input";
import { syncClientFolder } from "../lib/folderSync";
import { rememberFolder, startAutoSync, stopAutoSync } from "../lib/autoSync";
import { isDesktop, pickFolder } from "../lib/desktop";
import { faNum } from "../utils/format";
import { Surface } from "../components/ui/surface";

// 04/05/06/07 mockups — the automatic steps (workspace, brain) run in order
// behind the stepper, then the ingestion folder card (06) is the only user
// input (US-007); «شروع گفتگو» ends onboarding. In the cloud client the folder
// is on the owner's own machine (ADR-023), so step 06 opens a native picker and
// syncs the file listing; the server-side path variant stays for on-prem.
interface Status {
  organization_status: string;
  workspace_ready: boolean;
  brain_ready: boolean;
  knowledge_source: { id: string; path: string; status: string } | null;
  next_step: string;
}

interface SyncSummary {
  files: number;
  added: number;
  skipped: number;
  rejected: number;
  failed: number;
}

export default function Onboarding({ onStatus }: { onStatus: (status: Status) => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [checked, setChecked] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [fileCount, setFileCount] = useState<number | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [summary, setSummary] = useState<SyncSummary | null>(null);
  // The browser build cannot open a native picker; it keeps the manual path
  // field so an admin on a laptop is not blocked.
  const desktop = isDesktop();

  // `onStatus` is an inline callback from the parent, so it changes identity on
  // every parent render. Including it as a dependency would re-run the whole
  // bootstrap — three round trips and two POSTs — on each one. The callback is
  // held in a ref instead, so the effect can depend on nothing and still call
  // the current version.
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;

  async function refresh(): Promise<Status> {
    const next = await api<Status>("GET", "/auth/onboarding-status");
    setStatus(next);
    onStatusRef.current(next);
    return next;
  }

  // Runs exactly once per mount: the automatic steps below create the workspace
  // and the brain, so re-running them is not merely wasteful, it re-issues the
  // POSTs.
  useEffect(() => {
    (async () => {
      try {
        const next = await refresh();
        // 04/05: the automatic steps — run once, silently, in order.
        if (!next.workspace_ready) await api("POST", "/workspaces/initialize");
        const now = await refresh();
        if (!now.brain_ready) await api("POST", "/brain/initialize");
        const ready = await refresh();
        if (ready.knowledge_source?.path) setFolder(ready.knowledge_source.path);
        setBusy(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : "خطا");
        setBusy(false);
      }
    })();
  }, []);

  // PO request: the client keeps the folder in sync on its own. The loop asks
  // the server for the cadence, so the 30-minute interval stays an admin-panel
  // setting; manual sync stays available for "now".
  useEffect(() => {
    if (!desktop) return;
    const stop = startAutoSync();
    return stop;
  }, [desktop]);

  /** Native picker: pick, register, then sync the listing in one go. */
  async function chooseFolder() {
    setError(null);
    try {
      const picked = await pickFolder();
      if (!picked) return; // cancelled - not a failure
      setFolder(picked);
      await registerAndSync(picked);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }

  async function registerAndSync(folderPath: string) {
    setBusy(true);
    setError(null);
    setSummary(null);
    try {
      // US-007: the folder belongs to the owner's machine, so it is registered
      // as a client folder (never validated as a path on this server).
      const data = await api<{ id: string; file_state: string | number }>(
        "POST",
        "/knowledge-sources/client-folder",
        { path: folderPath },
      );
      setChecked(data.id);
      rememberFolder(folderPath); // the background loop picks this folder up
      setProgress({ done: 0, total: 0 });
      const result = await syncClientFolder(folderPath, (done, total) =>
        setProgress({ done, total }),
      );
      setFileCount(result.discovered_files);
      setSummary({
        files: result.discovered_files,
        added: result.added,
        skipped: result.skipped,
        rejected: result.rejected.length,
        failed: result.failed.length,
      });
      await refresh();
    } catch (e) {
      // Local (bridge) failures carry bare codes; give them a Persian reason.
      setError(localReason(e));
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  /** «بررسی و ثبت» in the browser/on-prem variant (server-side folder). */
  async function checkFolder() {
    if (desktop) {
      await registerAndSync(folder.trim());
      return;
    }
    setBusy(true);
    setError(null);
    try {
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
    setError(null);
    try {
      if (desktop) {
        const result = await syncClientFolder(folder, (done, total) =>
          setProgress({ done, total }),
        );
        setFileCount(result.discovered_files);
        setSummary({
          files: result.discovered_files,
          added: result.added,
          skipped: result.skipped,
          rejected: result.rejected.length,
          failed: result.failed.length,
        });
      } else {
        const data = await api<{ file_state: string | number }>(
          "POST",
          "/knowledge-sources/" + status.knowledge_source.id + "/scan",
        );
        if (typeof data.file_state === "number") setFileCount(data.file_state);
      }
    } catch (e) {
      setError(localReason(e));
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  // F: "شروع گفتگو" only re-published the status it already had, so with the
  // server still on next_step "knowledge_source" the click did nothing at all.
  // Ask the server again; the shell leaves this screen when it answers "chat".
  async function startChat() {
    setStarting(true);
    setError(null);
    try {
      const next = await refresh();
      if (next.next_step !== "chat") {
        setError("برای شروع گفتگو، پوشه اسناد را ثبت کنید.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setStarting(false);
    }
  }

  const stage = !status ? "workspace" : !status.workspace_ready ? "workspace" : !status.brain_ready ? "brain" : "folder";

  return (
    <section aria-label="راه‌اندازی سازمان">
      <AuthBrand title="راه‌اندازی سازمان" subtitle="چند گام کوتاه تا گفتگو با هوش سازمان." />
      <Stepper current={stage === "workspace" ? 4 : stage === "brain" ? 5 : 6} />

      {status?.next_step === "expired" && (
        <Surface className="p-7">
          <PanelHead icon={FolderOpen} tone="error" title="ثبت‌نام این سازمان منقضی شد" />
          <p className="text-caption text-muted-foreground">سازمان در بازه‌ی مجاز تکمیل نشد. از ابتدا ثبت‌نام کنید.</p>
          <LoadingButton variant="secondary" className="mt-4" onClick={() => { stopAutoSync(); clearToken(); location.reload(); }}>
            بازگشت به ورود
          </LoadingButton>
        </Surface>
      )}

      {status?.next_step !== "expired" && stage === "workspace" && (
        <Surface className="p-7">
          <PanelHead icon={Server} tone="violet" title="در حال آماده‌سازی فضای کار" hint="گام ۴ از ۶" />
          <p className="mb-2 text-caption text-muted-foreground">این مرحله خودکار انجام می‌شود؛ چند لحظه صبر کنید.</p>
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
              <LoadingButton variant="secondary" className="mt-3" onClick={() => location.reload()}>
                <RefreshCw aria-hidden />
                تلاش مجدد
              </LoadingButton>
            </div>
          )}
        </Surface>
      )}

      {status?.next_step !== "expired" && stage === "brain" && (
        <Surface className="p-7">
          <PanelHead icon={Sparkles} tone="teal" title="در حال ساخت هوش سازمان" hint="گام ۵ از ۶" />
          <p className="mb-2 text-caption text-muted-foreground">
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
              <LoadingButton variant="secondary" className="mt-3" onClick={() => location.reload()}>
                <RefreshCw aria-hidden />
                تلاش مجدد
              </LoadingButton>
            </div>
          )}
        </Surface>
      )}

      {status?.next_step !== "expired" && stage === "folder" && (
        <Surface className="p-7">
          <PanelHead icon={FolderSearch} tone="amber" title="تعیین پوشه اسناد" hint="گام ۶ از ۶" />
          <p className="mb-4 text-caption text-muted-foreground">
            {desktop
              ? "پوشه‌ای روی همین کامپیوتر انتخاب کنید؛ اسناد آن به دانش سازمان اضافه می‌شود و هر ۳۰ دقیقه به‌روز می‌شود."
              : "مسیر یک پوشه روی همین سرور را وارد کنید؛ اسناد آن به دانش سازمان اضافه می‌شود."}
          </p>

          {/* الگوی folder-pick ماک‌آپ (بازبینی پنجم): ردیف پوشه + مسیر mono */}
          <Field
            label="پوشه اسناد"
            required
            hint={desktop ? "با دکمهٔ انتخاب پوشه، مسیر به‌طور خودکار پر می‌شود" : "مثلاً /srv/hive-docs"}
          >
            <div className="flex flex-wrap items-center gap-3 rounded-[12px] border border-border bg-card p-2.5 ps-3">
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
                placeholder={desktop ? "ابتدا پوشه را انتخاب کنید" : "/srv/hive-docs"}
                readOnly={desktop}
                className="min-w-40 flex-1 border-0 font-mono text-caption shadow-none focus:ring-0"
                aria-label="مسیر پوشه اسناد"
              />
              {desktop && (
                <LoadingButton size="sm" variant="secondary" onClick={chooseFolder} disabled={busy}>
                  <FolderOpen aria-hidden />
                  انتخاب پوشه
                </LoadingButton>
              )}
              <LoadingButton
                size="sm"
                onClick={checkFolder}
                loading={busy}
                disabled={!folder.trim()}
              >
                {desktop ? "همگام‌سازی" : "بررسی و ثبت"}
              </LoadingButton>
            </div>
          </Field>

          <Banner tone="info">
            فایل‌های این پوشه در پویش بعدی (حداکثر هر ۳۰ دقیقه) شناسایی و پردازش می‌شوند. برای پردازش فوری از
            «همگام‌سازی اکنون» استفاده کنید. حجم هر فایل می‌تواند حداکثر ۲۵ مگابایت باشد.
          </Banner>

          {progress && (
            <div className="mt-4">
              <Banner tone="info">
                {progress.total > 0
                  ? `در حال ارسال فایل‌ها: ${faNum(progress.done)} از ${faNum(progress.total)}`
                  : "در حال خواندن فهرست فایل‌های پوشه…"}
              </Banner>
            </div>
          )}

          {error && (
            <div className="mt-4">
              <Banner tone="error" title="ثبت پوشه ناموفق بود.">{error}</Banner>
              <div className="mt-3 flex gap-2.5">
                {desktop && (
                  <LoadingButton variant="secondary" onClick={chooseFolder}>
                    <FolderOpen aria-hidden />
                    انتخاب پوشه دیگر
                  </LoadingButton>
                )}
                <LoadingButton
                  variant="secondary"
                  onClick={() => registerAndSync(folder.trim())}
                  disabled={!folder.trim()}
                >
                  <RefreshCw aria-hidden />
                  تلاش مجدد
                </LoadingButton>
              </div>
            </div>
          )}

          {checked && !error && (
            <div className="mt-4">
              <Banner
                tone="success"
                title={
                  fileCount !== null && fileCount > 0
                    ? `پوشه ثبت شد — ${faNum(fileCount)} فایل شناسایی شد.`
                    : "پوشه ثبت شد؛ در انتظار فایل است."
                }
              >
                {summary && (
                  <span className="block">
                    {faNum(summary.added)} فایل جدید به صف پردازش رفت
                    {summary.skipped > 0 && ` و ${faNum(summary.skipped)} فایل نادیده گرفته شد`}
                    {summary.rejected > 0 && ` و ${faNum(summary.rejected)} فایل بزرگ‌تر از ۲۵ مگابایت رد شد`}
                    {summary.failed > 0 && ` و ارسال ${faNum(summary.failed)} فایل ناموفق بود`}.
                  </span>
                )}
                می‌توانید همین حالا گفتگو را شروع کنید.
              </Banner>
            </div>
          )}

          {checked && (
            <div className="mt-5 flex gap-2.5">
              <LoadingButton variant="secondary" onClick={scanNow} loading={busy}>
                {desktop ? "همگام‌سازی اکنون" : "پویش اکنون"}
              </LoadingButton>
              <LoadingButton className="flex-1" onClick={startChat} loading={starting}>
                <House aria-hidden className="rtl:-scale-x-100" />
                شروع گفتگو
              </LoadingButton>
            </div>
          )}
        </Surface>
      )}
    </section>
  );
}

/** Client-side failures are bare codes: never show them raw to the owner. */
function localReason(exc: unknown): string {
  const code = exc instanceof Error ? exc.message : "";
  const known: Record<string, string> = {
    CLIENT_BRIDGE_MISSING: "این کار فقط در نسخهٔ ویندوزی برنامه امکان‌پذیر است.",
    NOT_A_DIRECTORY: "مسیر انتخاب‌شده یک پوشه نیست؛ دوباره انتخاب کنید.",
    EMPTY_PATH: "ابتدا پوشه را انتخاب کنید.",
    SCAN_FAILED: "خواندن فهرست فایل‌های پوشه ممکن نشد؛ دوباره تلاش کنید.",
    TOO_LARGE: "حجم این فایل از ۲۵ مگابایت بیشتر است.",
    FORMAT_NOT_ALLOWED: "قالب این فایل پشتیبانی نمی‌شود.",
    PATH_ESCAPE: "دسترسی به این فایل مجاز نیست.",
    NOT_A_FILE: "این مورد یک فایل نیست.",
    READ_FAILED: "خواندن این فایل ممکن نشد؛ ممکن است باز یا قفل باشد.",
  };
  if (known[code]) return known[code];
  if (exc instanceof Error && exc.message) return exc.message;
  return "انجام این کار ممکن نشد؛ دوباره تلاش کنید.";
}