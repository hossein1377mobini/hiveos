import { useEffect, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import { api, ApiError } from "../api";
import Stepper from "../Stepper";

const FA = "۰۱۲۳۴۵۶۷۸۹";
const toFa = (s: string) => String(s).replace(/\d/g, (d) => FA[+d]);

// Show the canonical "+98XXXXXXXXXX" as Persian-grouped digits: "+۹۸ ۹۱۲ ۳۴۵ ۶۷۸۹".
function phoneFa(phone: string): string {
  const d = phone.replace(/^\+98/, "");
  let g = d;
  if (d.length > 6) g = d.slice(0, 3) + " " + d.slice(3, 6) + " " + d.slice(6);
  else if (d.length > 3) g = d.slice(0, 3) + " " + d.slice(3);
  return "+" + toFa("98") + " " + toFa(g);
}

interface Props {
  phone: string;
  onDone: () => void;
  onBack: () => void;
}

export default function OtpVerify({ phone, onDone, onBack }: Props) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");
  const [codeErr, setCodeErr] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const didInit = useRef(false);

  async function send() {
    setError("");
    setSending(true);
    try {
      const r = await api.sendOtp({ phone });
      setCountdown(r.expiresInSeconds);
      setDigits(Array(6).fill(""));
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("برای ارسال مجدد کمی صبر کنید.");
      else setError((e as Error).message || "خطا در ارسال کد");
    } finally {
      setSending(false);
    }
  }

  // Send the first OTP on mount. The didInit ref guards against React 18 StrictMode
  // double-invoking effects in dev (which would otherwise fire send-otp twice -> 429).
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    send();
  }, []);

  // Single countdown clock; decrements to 0 and clamps there.
  useEffect(() => {
    const id = setInterval(() => setCountdown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, []);

  function setDig(i: number, ch: string) {
    let lat = "";
    if (/[0-9]/.test(ch)) lat = ch;
    else {
      const idx = FA.indexOf(ch);
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
    const lat = txt.replace(/[۰-۹]/g, (d) => String(FA.indexOf(d))).replace(/\D/g, "").slice(0, 6);
    if (!lat) return;
    const nd = Array(6).fill("");
    lat.split("").forEach((c, idx) => { nd[idx] = c; });
    setDigits(nd);
    refs.current[Math.min(lat.length, 5)]?.focus();
  }

  const filled = digits.every((d) => d !== "");

  async function verify() {
    if (!filled || verifying) return;
    setVerifying(true);
    setError("");
    setCodeErr(false);
    try {
      const r = await api.verifyOtp({ phone, code: digits.join("") });
      if (r.verified && r.userStatus === "active") onDone();
      else setError("تأیید انجام نشد.");
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 400) {
          setError("کد واردشده درست نیست.");
          setCodeErr(true);
          setDigits(Array(6).fill(""));
          refs.current[0]?.focus();
        } else if (e.status === 410) {
          setError("کد منقضی شده است. روی «ارسال مجدد» بزنید تا کد تازه دریافت کنید.");
        } else if (e.status === 429) {
          setError("ورود کد به‌طور موقت قفل شد. کمی بعد دوباره تلاش کنید.");
        } else {
          setError(e.message || "خطا در تأیید کد");
        }
      } else {
        setError((e as Error).message || "خطا در تأیید کد");
      }
    } finally {
      setVerifying(false);
    }
  }

  const timerLabel =
    toFa(String(Math.floor(countdown / 60)).padStart(2, "0")) +
    ":" +
    toFa(String(countdown % 60).padStart(2, "0"));

  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <Stepper active={2} />
      <div className="card" style={{ textAlign: "center" }}>
        <h2 style={{ marginTop: 0 }}>کد ۶ رقمی</h2>
        <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 6 }}>کد ارسال‌شده به شماره</p>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 15, direction: "ltr" }}>{phoneFa(phone)}</span>
          <button className="btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }} onClick={onBack} type="button">ویرایش</button>
        </div>

        <div className="otp" onPaste={onPaste}>
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => { refs.current[i] = el; }}
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
          {countdown > 0 ? (
            <>
              <span>کد تا</span>
              <span className="count">{timerLabel}</span>
              <span>معتبر است.</span>
            </>
          ) : (
            <button className="btn-ghost" onClick={send} disabled={sending} type="button">
              {sending ? "در حال ارسال…" : "ارسال مجدد کد"}
            </button>
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
    </div>
  );
}
