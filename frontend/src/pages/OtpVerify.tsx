import { KeyRound, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, clearToken } from "../api/client";
import { AuthBrand, faDigit, PanelHead, Stepper } from "../components/auth/parts";
import { Banner } from "../components/ui/banner";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";
import { normDigits } from "../utils/format";

// 03-otp-verify.html — US-003: six-box OTP with auto-advance + filled state,
// auto-submit on the sixth digit, 02:00 countdown then «ارسال مجدد» appears in
// the same spot, error state on the boxes. Business logic unchanged (send /
// resend / verify endpoints, TTL + cooldown from the server).
// 4-digit code per PO decision (CHANGE-029 / ADR-016 amendment 2026-09-08):
// the Melipayamak console OTP service generates and sends a 4-digit code.
const BOXES = 4;
const TIMER_SECONDS = 120;

export default function OtpVerify({ onVerified }: { onVerified: () => void }) {
  const [digits, setDigits] = useState<string[]>(Array(BOXES).fill(""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [timer, setTimer] = useState(TIMER_SECONDS);
  const [sent, setSent] = useState(false);
  const [devCode, setDevCode] = useState<string | null>(null);
  const sentOnce = useRef(false);
  const inputsRef = useRef<Array<HTMLInputElement | null>>([]);

  useEffect(() => {
    if (!sentOnce.current) {
      sentOnce.current = true;
      void api<{ dev_code?: string }>("POST", "/auth/send-otp")
        .then((res) => {
          setSent(true);
          if (res?.dev_code) setDevCode(res.dev_code);
        })
        .catch((e) => setError(e instanceof Error ? e.message : "خطا"));
    }
  }, []);

  useEffect(() => {
    if (timer <= 0) return;
    const t = setInterval(() => setTimer((v) => v - 1), 1000);
    return () => clearInterval(t);
  }, [timer]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((c) => c - 1), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const code = digits.join("");

  // Auto-verify once the last box is filled (mockup: no explicit submit).
  useEffect(() => {
    if (sent && code.length === BOXES && !code.includes("") && !busy) void verify(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  async function verify(value: string) {
    setBusy(true);
    setError(null);
    try {
      await api("POST", "/auth/verify-otp", { code: value });
      onVerified();
    } catch (e) {
      setError(e instanceof Error ? e.message : "کد واردشده درست نیست.");
      setDigits(Array(BOXES).fill(""));
      inputsRef.current[0]?.focus();
    } finally {
      setBusy(false);
    }
  }

  function setDigit(index: number, raw: string) {
    const clean = normDigits(raw).replace(/\D/g, "");
    if (!clean) {
      setDigits((d) => d.map((v, i) => (i === index ? "" : v)));
      return;
    }
    setDigits((d) => {
      const next = [...d];
      let cursor = index;
      for (const ch of clean) {
        if (cursor >= BOXES) break;
        next[cursor] = ch;
        cursor += 1;
      }
      const focusAt = Math.min(cursor, BOXES - 1);
      requestAnimationFrame(() => inputsRef.current[focusAt]?.focus());
      return next;
    });
  }

  function onKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputsRef.current[index - 1]?.focus();
      setDigits((d) => d.map((v, i) => (i === index - 1 ? "" : v)));
    }
  }

  async function resend() {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ dev_code?: string }>("POST", "/auth/resend-otp");
      if (res?.dev_code) setDevCode(res.dev_code);
      setCooldown(60);
      setTimer(TIMER_SECONDS);
      setDigits(Array(BOXES).fill(""));
      inputsRef.current[0]?.focus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  const mm = String(Math.floor(Math.max(0, timer) / 60)).padStart(2, "0");
  const ss = String(Math.max(0, timer) % 60).padStart(2, "0");

  return (
    <section aria-label="تأیید کد">
      <AuthBrand title="تأیید کد" subtitle="کد ارسال‌شده را وارد کنید." />
      <Stepper current={3} />

      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-7 shadow-card">
        {devCode && (
          <div className="mb-5" data-testid="dev-code">
            <Banner tone="success" title={`کد توسعه: ${devCode}`}>
              سرویس پیامک در این محیط آزمایشی است (mock) — کد بالا را در باکس‌های زیر وارد کنید.
            </Banner>
          </div>
        )}
        <PanelHead icon={KeyRound} tone="amber" title="کد تأیید" center />
        <p className="mt-2 text-center text-[13px] text-neutral-600">کد تأیید پیامک‌شده به شماره موبایل سازمان را وارد کنید.</p>

        <div className="mt-7 flex justify-center gap-2.5" dir="rtl">
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => {
                inputsRef.current[i] = el;
              }}
              value={d}
              onChange={(e) => setDigit(i, e.target.value)}
              onKeyDown={(e) => onKeyDown(i, e)}
              maxLength={2}
              inputMode="numeric"
              autoComplete="one-time-code"
              aria-label={`رقم ${faDigit(i + 1)}`}
              disabled={busy}
              className={cn(
                "size-[52px] rounded-[12px] border bg-neutral-0 p-0 text-center text-2xl font-bold text-neutral-900 transition-[border-color,box-shadow]",
                "focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50",
                d && "border-navy-600 bg-navy-50",
                error && "border-error focus:ring-error-bg",
                busy && "cursor-not-allowed bg-neutral-50 text-neutral-400",
              )}
            />
          ))}
        </div>

        <div className="mt-3.5 flex min-h-6 items-center justify-center gap-1.5 text-xs">
          {error ? (
            <span className="flex items-center gap-1.5 text-error">
              <ShieldAlert aria-hidden className="size-3.5" />
              {error}
            </span>
          ) : timer > 0 && sent ? (
            <span className="flex items-center gap-1.5 text-neutral-400">
              کد تا
              <span className="inline-block min-w-[44px] font-bold text-neutral-600" dir="ltr">
                {faDigit(mm)}:{faDigit(ss)}
              </span>
              معتبر است.
            </span>
          ) : (
            <Button variant="accent" size="xs" onClick={resend} loading={busy || cooldown > 0}>
              <RefreshCw aria-hidden />
              ارسال مجدد کد
            </Button>
          )}
        </div>

        <div className="mt-5">
          <Button className="w-full" onClick={() => void verify(code)} loading={busy} disabled={code.length < BOXES}>
            تأیید کد
          </Button>
          <button
            type="button"
            onClick={() => {
              clearToken();
              location.reload();
            }}
            className="mt-3 w-full cursor-pointer text-center text-xs text-neutral-600 underline-offset-4 hover:underline"
          >
            خروج از این حساب
          </button>
        </div>
      </div>
    </section>
  );
}