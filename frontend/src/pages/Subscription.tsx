import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { NavId } from "../components/AppShell";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { RetryNotice } from "../components/ui/retry";
import { faDate, faNum } from "../utils/format";
import { Surface } from "../components/ui/surface";

// 12-ai-access/04-subscription.html at mockup fidelity (hero status card +
// «اشتراک و اعتبار» explainer rows). US-1207 minimal model: the plan is
// granted/extended by the System Admin in the panel (epic-16), so the renewal
// / gateway blocks of the mockup are intentionally absent (business change —
// pattern kept, copy adjusted); «خرید اعتبار مکمل» routes to the wallet.
interface Subscription {
  plan: string;
  expires_at: string | null;
  expired: boolean;
}

const PLAN_FA: Record<string, string> = {
  monthly: "ماهانه",
  trial: "دوره آزمایشی",
};

export default function Subscription({ onNavigate }: { onNavigate?: (id: NavId) => void }) {
  const [sub, setSub] = useState<Subscription | null>(null);
  const [error, setError] = useState<string | null>(null);

  // PO request: a failed load shows the server's Persian reason + «تلاش مجدد».
  const load = useCallback(async () => {
    setError(null);
    try {
      const s = await api<{ subscription: Subscription }>("GET", "/auth/onboarding-status");
      setSub(s.subscription);
    } catch (e) {
      setSub(null);
      setError(e instanceof Error ? e.message : "دریافت وضعیت اشتراک ناموفق بود.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!sub) {
    if (error) {
      return <RetryNotice message={error} onRetry={() => void load()} testId="subscription-retry" />;
    }
    return <p className="text-sm text-muted-foreground">در حال بارگذاری…</p>;
  }

  const daysLeft = sub.expires_at
    ? Math.max(
        0,
        Math.ceil((new Date(sub.expires_at).getTime() - Date.now()) / (24 * 3600 * 1000)),
      )
    : null;
  const planFa = PLAN_FA[sub.plan] ?? sub.plan;

  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-label="اشتراک">
      <div className="flex flex-wrap items-start gap-3.5">
        <div>
          <h1 className="text-[19px] font-extrabold text-foreground">اشتراک</h1>
          <p className="mt-[3px] text-[13px] text-muted-foreground">
            دسترسی به خود برنامه از طریق اشتراک دوره‌ای — مستقل از اعتبار مصرف هوش سازمان.
          </p>
        </div>
        <div className="ms-auto flex items-center gap-2">
          <LoadingButton variant="secondary" size="sm" onClick={() => onNavigate?.("wallet")}>
            خرید اعتبار مکمل
          </LoadingButton>
        </div>
      </div>

      {sub.expired && (
        <Banner tone="error" title="اشتراک شما منقضی شده است." data-testid="sub-expired-banner">
          اجرای هوش سازمان متوقف است؛ اعتبار باقی‌مانده کیف پول شما محفوظ می‌ماند. برای ادامه، از مدیر سامانه تمدید بخواهید.
        </Banner>
      )}

      {/* وضعیت اشتراک — الگوی wallet-hero (mockup §۲۱) */}
      <div className="relative overflow-hidden rounded-[20px] bg-primary px-7 py-[26px] text-primary-foreground shadow-[0_14px_34px_rgba(43,58,115,0.3)]">
        <span aria-hidden className="absolute -end-[30px] -top-[30px] size-40 rounded-full bg-white/[0.06]" />
        <div className="text-xs font-bold opacity-75">وضعیت اشتراک</div>
        <div className="mt-1.5 text-[22px] font-extrabold" data-testid="plan">
          {sub.expired ? "منقضی شده" : `فعال — بسته‌ی ${planFa}`}
        </div>
        <div className="mt-2 text-xs opacity-85" data-testid="expiry">
          {sub.expires_at
            ? `پایان دوره: ${faDate(sub.expires_at)}${daysLeft && daysLeft > 0 ? ` · ${faNum(daysLeft)} روز باقی‌مانده` : ""}`
            : "بدون انقضا"}
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        تمدید و تغییر پلن توسط مدیر سامانه در پنل مدیریت انجام می‌شود.
      </p>

      {/* اشتراک و اعتبار — تفاوت‌ها (setting-row, mockup) */}
      <Surface className="p-6">
        <h2 className="mb-3 text-[15px] font-extrabold text-foreground">اشتراک و اعتبار — تفاوت‌ها</h2>
        <div className="border-b border-border py-3.5 last:border-b-0">
          <div className="text-[13.5px] font-bold text-foreground">اشتراک فعال</div>
          <div className="mt-0.5 max-w-[520px] text-xs text-muted-foreground">
            دسترسی به خود برنامه را تأمین می‌کند؛ بدون آن، اجرای هوش سازمان متوقف است.
          </div>
        </div>
        <div className="border-b border-border py-3.5 last:border-b-0">
          <div className="text-[13.5px] font-bold text-foreground">اعتبار بسته‌ی اشتراک</div>
          <div className="mt-0.5 max-w-[520px] text-xs text-muted-foreground">
            با خرید/تمدید، یک‌جا به کیف پول اضافه می‌شود و با مصرف کسر می‌شود.
          </div>
        </div>
        <div className="border-b border-border py-3.5 last:border-b-0">
          <div className="text-[13.5px] font-bold text-foreground">اعتبار مکمل</div>
          <div className="mt-0.5 max-w-[520px] text-xs text-muted-foreground">
            در هر لحظه از دوره قابل درخواست است — از «کیف پول ← شارژ حساب».
          </div>
        </div>
        <div className="border-b border-border py-3.5 last:border-b-0">
          <div className="text-[13.5px] font-bold text-foreground">پایان دوره</div>
          <div className="mt-0.5 max-w-[520px] text-xs text-muted-foreground">
            اعتبار باقی‌مانده حفظ می‌شود؛ تا تمدید اشتراک، اجرای هوش سازمان متوقف می‌ماند.
          </div>
        </div>
        <div className="py-3.5 last:border-b-0">
          <div className="text-[13.5px] font-bold text-foreground">دوره آزمایشی (سازمان جدید)</div>
          <div className="mt-0.5 max-w-[520px] text-xs text-muted-foreground">
            با اعتبار خوش‌آمد — بدون نیاز به اشتراک. مدت و مقدار اعتبار از پنل ادمین تعیین می‌شود.
          </div>
        </div>
      </Surface>
    </section>
  );
}
