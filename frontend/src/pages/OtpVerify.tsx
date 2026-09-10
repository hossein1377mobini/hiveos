import { useEffect, useRef, useState } from "react";
import { api, clearToken } from "../api/client";

// 03-otp-verify.html — US-003: ۶ رقم، TTL ۵ دقیقه، ارسال مجدد با شمارش معکوس.
export default function OtpVerify({ onVerified }: { onVerified: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [sent, setSent] = useState(false);
  const sentOnce = useRef(false);

  useEffect(() => {
    if (!sentOnce.current) {
      sentOnce.current = true;
      void api("POST", "/auth/send-otp")
        .then(() => setSent(true))
        .catch((e) => setError(e instanceof Error ? e.message : "خطا"));
    }
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((c) => c - 1), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  async function resend() {
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ resend_available_at: string }>("POST", "/auth/resend-otp");
      setCooldown(60);
      setSent(true);
      void data;
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("POST", "/auth/verify-otp", { code });
      onVerified();
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
      <h1 className="text-lg font-bold">تأیید شماره موبایل</h1>
      <p className="mt-1 text-sm text-neutral-600">کد ۶ رقمی پیامک‌شده را وارد کنید.</p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <input
          dir="ltr"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          inputMode="numeric"
          maxLength={6}
          className="w-full rounded-control border border-neutral-200 px-3 py-2 text-center text-lg tracking-[0.5em]"
        />
        {error && <div className="rounded-control bg-error-bg p-3 text-sm text-error">{error}</div>}
        <button type="submit" disabled={busy || !sent} className="w-full rounded-control bg-navy-600 py-2 font-bold text-white disabled:opacity-60">
          تأیید
        </button>
        <button type="button" onClick={resend} disabled={busy || cooldown > 0} className="w-full rounded-control border border-neutral-200 py-2 text-sm disabled:opacity-60">
          {cooldown > 0 ? `ارسال مجدد پس از ${cooldown} ثانیه` : "ارسال مجدد کد"}
        </button>
        <button
          type="button"
          onClick={() => {
            clearToken();
            location.reload();
          }}
          className="w-full text-center text-xs text-neutral-600 underline"
        >
          خروج از این حساب
        </button>
      </form>
    </section>
  );
}
