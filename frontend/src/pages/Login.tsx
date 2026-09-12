import { useState } from "react";
import { api, ApiError, setToken } from "../api/client";
import { sanitizeUsernameInput, usernameError } from "../utils/username";
import { Surface } from "../components/ui/surface";

interface LoginData {
  user_id: string;
  organization_id: string;
  session: { token: string; expires_at: string };
}

const HOUSE_SVG = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    <polyline points="9 22 9 12 15 12 15 22" />
  </svg>
);

const EYE_SVG = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const ALERT_SVG = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="8" x2="12" y2="12" />
    <line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);

// 00-login.html fidelity: brand block, mono LTR username, password eye toggle,
// error banner with lock guidance. ورود بازگشتی — پیام خطا فیلد را فاش نمی‌کند.
export default function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api<LoginData>("POST", "/auth/login", { username, password });
      setToken(data.session.token);
      onDone();
    } catch (e) {
      // S1 (external review): the backend signals lockout with the ACCOUNT_LOCKED
      // code, not with a Persian message string.
      const wasLocked = e instanceof ApiError && e.code === "ACCOUNT_LOCKED";
      setLocked(wasLocked);
      // PO request: never replace the real cause (lockout, rate limit, server
      // down) with a canned "wrong password" - show the mapped Persian text.
      setError(e instanceof Error ? e.message : "ورود ناموفق بود؛ دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page w-full">
      <div className="brand mb-5 text-center">
        <span className="logo-box inline-flex h-[52px] w-[52px] items-center justify-center rounded-[14px] bg-navy-600 text-white shadow-[0_8px_20px_rgba(43,58,115,0.25)] [&>svg]:h-[26px] [&>svg]:w-[26px]">
          {HOUSE_SVG}
        </span>
        <h1 className="mt-3.5 text-[21px] font-extrabold">ورود به HiveOS</h1>
        <p className="mt-1 text-[13px] text-neutral-600">با نام کاربری و رمز عبور حساب خود وارد شوید.</p>
      </div>

      <Surface className="p-7">
        <form onSubmit={submit} noValidate={false}>
          <div className="mb-[18px]">
            <label className="mb-1.5 block text-[13px] font-bold">
              نام کاربری <span className="text-error">*</span>
            </label>
            <input
              type="text"
              dir="ltr"
              className="mono w-full rounded-[10px] border border-neutral-200 bg-neutral-0 px-[13px] py-[11px] text-left text-[14px] transition-colors placeholder:text-neutral-400 focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50"
              placeholder="manager.ar"
              autoComplete="username"
              value={username}
              minLength={3}
              maxLength={50}
              onChange={(e) => setUsername(sanitizeUsernameInput(e.target.value))}
              required
            />
            {username.length > 0 && usernameError(username) && (
              <p className="mt-1.5 text-[12px] text-error">{usernameError(username)}</p>
            )}
          </div>

          <div className="mb-[18px]">
            <label className="mb-1.5 block text-[13px] font-bold">
              رمز عبور <span className="text-error">*</span>
            </label>
            <div className="relative" dir="ltr">
              <input
                type={showPw ? "text" : "password"}
                dir="ltr"
                className="w-full rounded-[10px] border border-neutral-200 bg-neutral-0 px-[13px] py-[11px] pe-12 text-left text-[14px] transition-colors placeholder:text-neutral-400 focus:border-navy-600 focus:outline-none focus:ring-[3px] focus:ring-navy-50"
                placeholder="••••••••"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                aria-label="نمایش رمز"
                onClick={() => setShowPw((v) => !v)}
                className="absolute end-3 top-1/2 -translate-y-1/2 rounded-[6px] p-1 text-neutral-400 transition-colors hover:bg-neutral-50 hover:text-neutral-600"
              >
                <span className="block h-5 w-5 [&>svg]:h-5 [&>svg]:w-5">{EYE_SVG}</span>
              </button>
            </div>
          </div>

          {error && (
            <div
              className="mb-4 flex items-start gap-2.5 rounded-[10px] border border-error bg-error-bg p-3 text-[13px] text-error"
              role="alert"
            >
              <span className="mt-0.5 block h-[18px] w-[18px] shrink-0 [&>svg]:h-[18px] [&>svg]:w-[18px]">{ALERT_SVG}</span>
              <div>
                <div className="font-extrabold">
                  {locked ? "ورود موقتاً قفل شد." : "نام کاربری یا رمز عبور درست نیست."}
                </div>
                <div className="mt-1 text-neutral-600">
                  {locked
                    ? "۱۵ دقیقه بعد دوباره تلاش کنید."
                    : "دوباره تلاش کنید. پس از ۵ تلاش ناموفق، ورود ۱۵ دقیقه قفل می‌شود."}
                </div>
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-[10px] bg-navy-600 px-5 py-3 text-[14px] font-bold text-white shadow-[0_3px_12px_rgba(43,58,115,0.28)] transition-all hover:bg-navy-800 hover:shadow-[0_6px_18px_rgba(43,58,115,0.34)] disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
          >
            {busy ? "در حال ورود…" : "ورود"}
          </button>
        </form>
      </Surface>
    </div>
  );
}
