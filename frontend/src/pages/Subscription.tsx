import { useEffect, useState } from "react";
import { api } from "../api/client";

// US-1207 minimal subscription (RG-21): the plan is granted/extended by the
// System Admin in the panel; the organization only sees its state here.
interface Subscription {
  plan: string;
  expires_at: string | null;
  expired: boolean;
}

export default function Subscription() {
  const [sub, setSub] = useState<Subscription | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const s = await api<{ subscription: Subscription }>("GET", "/auth/onboarding-status");
        setSub(s.subscription);
      } catch {
        setError("دریافت وضعیت اشتراک ناموفق بود.");
      }
    })();
  }, []);

  if (!sub) return <p className="text-sm text-neutral-600">{error ?? "در حال بارگذاری…"}</p>;

  const daysLeft = sub.expires_at
    ? Math.max(
        0,
        Math.ceil((new Date(sub.expires_at).getTime() - Date.now()) / (24 * 3600 * 1000)),
      )
    : null;

  return (
    <section className="mx-auto max-w-xl space-y-4" aria-label="اشتراک">
      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
        <p className="text-sm text-neutral-600">پلن فعلی</p>
        <p className="mt-1 text-3xl font-bold" data-testid="plan">
          {sub.plan}
        </p>
        <p className="mt-2 text-sm text-neutral-600" data-testid="expiry">
          {sub.expires_at
            ? daysLeft && daysLeft > 0
              ? daysLeft + " روز باقی‌مانده"
              : "منقضی شده"
            : "بدون انقضا"}
        </p>
        {sub.expired && (
          <p role="alert" className="mt-3 rounded-card bg-red-50 p-3 text-sm text-red-800">
            پلن سازمان منقضی شده است؛ برای ادامه، از مدیر سامانه تمدید بخواهید.
          </p>
        )}
      </div>
      <p className="text-xs text-neutral-500">
        تمدید و تغییر پلن توسط مدیر سامانه در پنل مدیریت انجام می‌شود.
      </p>
    </section>
  );
}
