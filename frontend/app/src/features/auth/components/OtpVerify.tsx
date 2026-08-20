import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import { authApi } from "../../../services/authApi";
import { ApiError, describeError } from "../../../services/http";
import { FA_DIGITS, toFa } from "../../../utils/persian";

// Show the canonical "+98XXXXXXXXXX" as Persian-grouped digits: "+۹۸ ۹۱۲ ۳۴۵ ۶۷۸۹".
function phoneFa(phone: string): string {
  const d = phone.replace(/^\+98/, "");
  let g = d;
  if (d.length > 6) g = d.slice(0, 3) + " " + d.slice(3, 6) + " " + d.slice(6);
  else if (d.length > 3) g = d.slice(0, 3) + " " + d.slice(3);
  return "+" + toFa("98") + " " + toFa(g);
}

// "MM:SS" rendered with Persian digits.
function mmss(total: number): string {
  return toFa(String(Math.floor(total / 60)).padStart(2, "0")) + ":" + toFa(String(total % 60).padStart(2, "0"));
}

interface Props {
  phone: string;
  onDone: () => void;
  onBack: () => void;
}

export default function OtpVerify({ phone, onDone, onBack }: Props) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [expiresIn, setExpiresIn] = useState(0); // OTP lifetime countdown
  const [resendIn, setResendIn] = useState(0); // independent resend cooldown
  const [sending, setSending] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");
  const [codeErr, setCodeErr] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const didInit = useRef(false);
  const mounted = useRef(true);

  const send = useCallback(async (kind: "send" | "resend" = "send") => {
    if (!mounted.current) return;
    setError("");
    setSending(true);
    try {
      const r =
        kind === "resend" ? await authApi.resendOtp({ phone }) : await authApi.sendOtp({ phone });
      if (!mounted.current) return;
      setExpiresIn(r.expiresInSeconds);
      setResendIn(r.resendAfterSeconds);
      setDigits(Array(6).fill(""));
    } catch (e) {
      if (!mounted.current) return;
      if (e instanceof ApiError && e.status === 429) {
        // Carry the server's resend cooldown forward.
        const rs = (e.details as { resendAfterSeconds?: number } | undefined)?.resendAfterSeconds;
        if (typeof rs === "number" && rs > 0) setResendIn(rs);
        setError("درخواست‌ها زیاد شده است؛ کمی صبر کنید و دوباره تلاش کنید.");
      } else {
        setError(describeError(e, "خطا در ارسال کد"));
      }
    } finally {
      if (mounted.current) setSending(false);
    }
  }, [phone]);

  // Unmount guard: stop all setState once the component goes away.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Send the first OTP on mount. The didInit ref guards against React StrictMode
  // double-invoking effects in dev (which would otherwise fire send-otp twice -> 429).
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    void send();
  }, [send]);

  // Two independent countdowns: OTP expiry and resend cooldown.
  useEffect(() => {
    const id = setInterval(() => {
      setExpiresIn((c) => (c > 0 ? c - 1 : 0));
      setResendIn((c) => (c > 0 ? c - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  function setDig(i: number, ch: string) {
    let lat = "";
    if (/[0-9]/.test(ch)) lat = ch;
    else {
      const idx = FA_DIGITS.indexOf(ch);
      if (idx >= 0) lat = String(idx);
    }
    const nd = [...digits];
    nd[i] = lat;
    setDigits(nd);
    if (lat && i < 5) refs.current[i + 1]?.focus();
  }

  function onKeyDown(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[i] && i > 0) refs.current[i - 1]?.focus();
  }

  function onPaste(e: ClipboardEvent<HTMLDivElement>) {
    e.preventDefault();
    const txt = e.clipboardData.getData("text");
    const lat = txt.replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d))).replace(/\D/g, "").slice(0, 6);
    if (!lat) return;
    const nd = Array(6).fill("");
    lat.split("").forEach((c, idx) => {
      nd[idx] = c;
    });
    setDigits(nd);
    refs.current[Math.min(lat.length, 5)]?.focus();
  }

  const filled = digits.every((d) => d !== "");

  async function verify() {
    const code = digits.join("");
    if (code.length !== 6 || verifying) return;
    setVerifying(true);
    setError("");
    setCodeErr(false);
    try {
      const r = await authApi.verifyOtp({ phone, code });
      if (!mounted.current) return;
      if (r.verified && r.userStatus === "active") onDone();
      else setError("تأیید انجام نشد.");
    } catch (e) {
      if (!mounted.current) return;
      if (e instanceof ApiError && e.status === 400) {
        setError("کد واردشده درست نیست.");
        setCodeErr(true);
        setDigits(Array(6).fill(""));
        refs.current[0]?.focus();
      } else {
        setError(describeError(e, "خطا در تأیید کد"));
      }
    } finally {
      if (mounted.current) setVerifying(false);
    }
  }

  return (
    <div className="card" style={{ textAlign: "center" }}>
      <h2 style={{ marginTop: 0 }}>کد ۶ رقمی</h2>
      <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 6 }}>کد ارسال‌شده به شماره</p>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 15, direction: "ltr" }}>{phoneFa(phone)}</span>
        <button className="btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }} onClick={onBack} type="button">ویرایش</button>
      </div>

      <div className="otp" role="group" aria-label="کد تأیید ۶ رقمی" onPaste={onPaste}>
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            value={d ? toFa(d) : ""}
            onChange={(e) => setDig(i, e.target.value.slice(-1))}
            onKeyDown={(e) => onKeyDown(i, e)}
            maxLength={1}
            inputMode="numeric"
            aria-label={`رقم ${toFa(String(i + 1))}`}
            className={[d ? "filled" : "", codeErr ? "err" : ""].join(" ").trim()}
          />
        ))}
      </div>

      <div className="timer">
        {expiresIn > 0 ? (
          <span>
            کد تا <span className="count">{mmss(expiresIn)}</span> معتبر است.
          </span>
        ) : (
          <span>کد منقضی شده است.</span>
        )}
      </div>

      <div className="timer">
        {sending ? (
          <button className="btn-ghost" type="button" disabled>در حال ارسال…</button>
        ) : resendIn > 0 ? (
          <button className="btn-ghost" type="button" disabled>
            ارسال مجدد تا {mmss(resendIn)}
          </button>
        ) : (
          <button className="btn-ghost" type="button" onClick={() => void send("resend")}>ارسال مجدد کد</button>
        )}
      </div>

      {error && <div className="field-error" style={{ justifyContent: "center", marginTop: 12 }}>{error}</div>}

      <button
        className="btn-primary"
        onClick={verify}
        disabled={!filled || verifying}
        type="button"
        style={{ width: "100%", marginTop: 24 }}
      >
        {verifying ? "در حال تأیید…" : "تأیید"}
      </button>
    </div>
  );
}
