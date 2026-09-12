import { Eye, EyeOff, ShieldCheck, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api, setToken } from "../api/client";
import { AuthBrand, Field, PanelHead, Stepper } from "../components/auth/parts";
import { Banner } from "../components/ui/banner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { cn } from "../lib/utils";
import { normDigits } from "../utils/format";
import { sanitizeUsernameInput, usernameError } from "../utils/username";

// 02-owner-account.html — US-002: first account + role assignment. Global
// stepper at step ۲, panel head, +98 mobile input group (design-system §6),
// password eye + live checklist (mockup), username availability check kept.
export default function OwnerAccount({
  organizationId,
  onDone,
}: {
  organizationId: string;
  onDone: (sessionToken: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [available, setAvailable] = useState<boolean | null>(null);
  const [mobile, setMobile] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (username.length < 3) {
      setAvailable(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const data = await api<{ available: boolean }>(
          "GET",
          `/auth/username-available?username=${encodeURIComponent(username)}`,
        );
        setAvailable(data.available);
      } catch {
        setAvailable(null);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [username]);

  const checks = [
    { label: "حداقل ۸ کاراکتر", ok: password.length >= 8 },
    { label: "یک حرف بزرگ", ok: /[A-Z]/.test(password) },
    { label: "یک عدد", ok: /[0-9]/.test(password) },
    { label: "یک نماد", ok: /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(password) },
  ];

  // Mockup mobile group: digits only (Persian digits normalized), display hint
  // +98; submission keeps the backend's 09xxxxxxxxx format.
  const mobileDigits = normDigits(mobile).replace(/\D/g, "");
  const normalizedMobile =
    mobileDigits.startsWith("9") && mobileDigits.length === 10
      ? "0" + mobileDigits
      : mobileDigits;
  const mobileInvalid = mobileDigits.length > 0 && !/^09\d{9}$/.test(normalizedMobile);
  const pwdMismatch = confirmPassword.length > 0 && confirmPassword !== password;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (mobileInvalid || pwdMismatch) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ session: { token: string } }>("POST", "/auth/owner", {
        organization_id: organizationId,
        username,
        mobile: normalizedMobile,
        password,
        confirm_password: confirmPassword,
      });
      // The bootstrap session drives send-otp/verify-otp; get_auth_context
      // slides it to a fresh TTL at verify time (US-003/IAM).
      setToken(data.session.token);
      onDone(data.session.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="حساب مدیر سازمان">
      <AuthBrand title="حساب مدیر سازمان" subtitle="حساب اول سازمان و نقش مدیر را بسازید." />
      <Stepper current={2} />

      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-7 shadow-card">
        <PanelHead icon={UserRound} title="حساب مدیر سازمان" hint="گام ۲ از ۶" />
        <form onSubmit={submit}>
          <Field
            label="نام کاربری"
            required
            error={usernameError(username) && username.length > 0 ? usernameError(username) : available === false ? "این نام کاربری آزاد نیست." : undefined}
            hint={!usernameError(username) && username.length >= 3 ? (available === true ? "این نام کاربری آزاد است." : "در حال بررسی…") : "حروف انگلیسی، ارقام و «.» و «@» — بین ۳ تا ۵۰ کاراکتر."}
          >
            <Input
              dir="ltr"
              value={username}
              onChange={(e) => setUsername(sanitizeUsernameInput(e.target.value))}
              required
              minLength={3}
              maxLength={50}
              className="font-mono"
              placeholder="manager.ar"
              autoComplete="username"
            />
          </Field>

          <Field label="شماره موبایل" required error={mobileInvalid ? "شماره موبایل معتبر نیست (مثلاً 9123456789)." : undefined}>
            {/* الگوی +۹۸ (design-system §6): قاب پیشوند در لبه چپ، رادیوس چپ */}
            <div className="flex" dir="ltr">
              <span
                aria-hidden
                className="flex select-none items-center justify-center rounded-[10px] border border-neutral-200 border-e-0 bg-neutral-50 px-3 text-sm font-bold text-neutral-600"
              >
                +۹۸
              </span>
              <Input
                dir="ltr"
                inputMode="numeric"
                value={mobile}
                onChange={(e) => setMobile(normDigits(e.target.value).replace(/[^0-9 ]/g, ""))}
                required
                placeholder="912 345 6789"
                className="rounded-e-[10px] rounded-s-none text-left"
                autoComplete="tel-national"
              />
            </div>
          </Field>

          <Field label="رمز عبور" required error={pwdMismatch ? undefined : undefined}>
            <div className="relative">
              <Input
                type={showPwd ? "text" : "password"}
                dir="ltr"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="pe-11"
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowPwd((v) => !v)}
                aria-label={showPwd ? "پنهان‌کردن رمز" : "نمایش رمز"}
                className="absolute end-2 top-1/2 -translate-y-1/2 cursor-pointer rounded-[6px] p-1 text-neutral-400 transition-colors hover:bg-neutral-50 hover:text-neutral-600"
              >
                {showPwd ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
              {checks.map((c) => (
                <span
                  key={c.label}
                  className={cn("flex items-center gap-1.5 text-[11.5px]", c.ok ? "text-success" : "text-neutral-400")}
                >
                  <span aria-hidden className={cn("size-1.5 rounded-full", c.ok ? "bg-success" : "bg-neutral-300")} />
                  {c.label}
                </span>
              ))}
            </div>
          </Field>

          <Field label="تکرار رمز عبور" required error={pwdMismatch ? "تکرار رمز عبور با رمز عبور یکسان نیست." : undefined}>
            <Input
              type="password"
              dir="ltr"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className={cn(pwdMismatch && "border-error focus:ring-error-bg")}
              autoComplete="new-password"
            />
          </Field>

          {error && (
            <div className="mb-4">
              <Banner tone="error">{error}</Banner>
            </div>
          )}
          <Button type="submit" className="w-full" loading={busy}>
            <ShieldCheck aria-hidden />
            ایجاد حساب و دریافت کد تأیید
          </Button>
        </form>
      </div>
    </section>
  );
}
