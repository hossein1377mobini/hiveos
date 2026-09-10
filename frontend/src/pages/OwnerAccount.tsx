import { useEffect, useState } from "react";
import { api, setToken } from "../api/client";

// 02-owner-account.html — US-002: first account + role assignment.
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

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ session: { token: string } }>("POST", "/auth/owner", {
        organization_id: organizationId,
        username,
        mobile,
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
    <section className="mx-auto w-full max-w-md rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
      <h1 className="text-lg font-bold">حساب مالک سازمان</h1>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <label className="block">
          <span className="text-sm font-semibold">نام کاربری</span>
          <input dir="ltr" value={username} onChange={(e) => setUsername(e.target.value)} required className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-left" />
          {available === false && <span className="text-xs text-error">این نام کاربری آزاد نیست.</span>}
          {available === true && <span className="text-xs text-success">آزاد است.</span>}
        </label>
        <label className="block">
          <span className="text-sm font-semibold">موبایل</span>
          <input dir="ltr" value={mobile} onChange={(e) => setMobile(e.target.value)} required placeholder="09121234567" className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-left" />
        </label>
        <label className="block">
          <span className="text-sm font-semibold">رمز عبور</span>
          <input type="password" dir="ltr" value={password} onChange={(e) => setPassword(e.target.value)} required className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-left" />
        </label>
        <label className="block">
          <span className="text-sm font-semibold">تکرار رمز عبور</span>
          <input type="password" dir="ltr" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-left" />
        </label>
        {error && <div className="rounded-control bg-error-bg p-3 text-sm text-error">{error}</div>}
        <button type="submit" disabled={busy || available === false} className="w-full rounded-control bg-navy-600 py-2 font-bold text-white disabled:opacity-60">
          {busy ? "..." : "ادامه"}
        </button>
      </form>
    </section>
  );
}
