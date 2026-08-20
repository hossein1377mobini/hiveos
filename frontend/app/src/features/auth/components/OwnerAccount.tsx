import { useState, type FormEvent } from "react";
import { authApi } from "../../../services/authApi";
import { describeError } from "../../../services/http";
import { normalizePhone, formatPhone } from "../../../utils/persian";

// Contract (docs/openapi.yaml): phone ^\+98\d{10}$; password >=8 with upper, lower,
// digit and an ASCII symbol (Persian symbols REJECTED); confirmPassword === password.
const ASCII_SYMBOL_RE = /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?~`]/;

interface Props {
  onDone: (r: { userId: string; phone: string }) => void;
  onBack: () => void;
  initialPhone?: string;
}

export default function OwnerAccount({ onDone, onBack, initialPhone }: Props) {
  const [phone, setPhone] = useState(initialPhone ?? "+98");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [fieldErrs, setFieldErrs] = useState<{ phone?: string; pwd?: string; confirm?: string }>({});
  const [apiError, setApiError] = useState("");
  const [busy, setBusy] = useState(false);

  const phoneOk = /^\+98\d{10}$/.test(phone);
  const checks = [
    { label: "حداقل ۸ کاراکتر", ok: password.length >= 8 },
    { label: "یک حرف بزرگ", ok: /[A-Z]/.test(password) },
    { label: "یک حرف کوچک", ok: /[a-z]/.test(password) },
    { label: "یک عدد", ok: /[0-9]/.test(password) },
    { label: "یک نماد", ok: ASCII_SYMBOL_RE.test(password) },
  ];
  const pwdOk = checks.every((c) => c.ok);

  function validate(): boolean {
    const errs: { phone?: string; pwd?: string; confirm?: string } = {};
    if (!phoneOk) errs.phone = "شماره موبایل باید ۱۰ رقم بعد از ۹۸+ باشد.";
    if (!pwdOk) errs.pwd = "رمز عبور باید حداقل ۸ کاراکتر و شامل حرف بزرگ، حرف کوچک، عدد و نماد باشد.";
    if (!confirm) errs.confirm = "تکرار رمز عبور را وارد کنید.";
    else if (confirm !== password) errs.confirm = "تکرار رمز با رمز یکسان نیست.";
    setFieldErrs(errs);
    return Object.keys(errs).length === 0;
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    setApiError("");
    if (!validate()) return;
    setBusy(true);
    try {
      const res = await authApi.createOwner({ phone, password, confirmPassword: confirm });
      onDone({ userId: res.userId, phone });
    } catch (err) {
      setApiError(describeError(err, "خطا در ایجاد حساب مدیر", "این شماره پیش‌تر ثبت شده است."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>اطلاعات حساب مدیر</h2>

      <form onSubmit={submit}>
        <div className={`field ${fieldErrs.phone ? "invalid" : ""}`}>
          <label htmlFor="owner-phone">شماره موبایل <span style={{ color: "var(--err)" }}>*</span></label>
          <input
            id="owner-phone"
            className="monospace"
            type="tel"
            inputMode="numeric"
            dir="ltr"
            value={formatPhone(phone)}
            onChange={(e) => {
              setPhone(normalizePhone(e.target.value));
              if (fieldErrs.phone) setFieldErrs((f) => ({ ...f, phone: undefined }));
            }}
            placeholder="+98 912 345 6789"
          />
          <span className="hint">فقط رقم؛ ۱۰ رقم بعد از کد ۹۸+.</span>
          {fieldErrs.phone && <span className="field-error">{fieldErrs.phone}</span>}
        </div>

        <div className="field">
          <label htmlFor="owner-password">رمز عبور <span style={{ color: "var(--err)" }}>*</span></label>
          <div className="pw-wrap">
            <input
              id="owner-password"
              type={showPwd ? "text" : "password"}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (fieldErrs.pwd) setFieldErrs((f) => ({ ...f, pwd: undefined }));
              }}
              placeholder="••••••••"
            />
            <button type="button" className="eye" aria-label={showPwd ? "پنهان‌کردن رمز" : "نمایش رمز"} onClick={() => setShowPwd((v) => !v)}>
              {showPwd ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              )}
            </button>
          </div>
          <div className="checklist">
            {checks.map((c) => (
              <span key={c.label} className={`check ${c.ok ? "ok" : ""}`}>
                <span className="dot"></span>{c.label}
              </span>
            ))}
          </div>
          {fieldErrs.pwd && <span className="field-error">{fieldErrs.pwd}</span>}
        </div>

        <div className={`field ${fieldErrs.confirm ? "invalid" : ""}`}>
          <label htmlFor="owner-confirm">تکرار رمز عبور <span style={{ color: "var(--err)" }}>*</span></label>
          <input
            id="owner-confirm"
            type={showPwd ? "text" : "password"}
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              if (fieldErrs.confirm) setFieldErrs((f) => ({ ...f, confirm: undefined }));
            }}
            placeholder="••••••••"
          />
          {fieldErrs.confirm && <span className="field-error">{fieldErrs.confirm}</span>}
        </div>

        {apiError && <div className="alerts"><div className="alert error">{apiError}</div></div>}

        <div className="actions-row">
          <button type="button" className="btn-secondary" onClick={onBack}>بازگشت</button>
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? "در حال ساخت…" : "ایجاد حساب"}</button>
        </div>
      </form>
    </div>
  );
}
