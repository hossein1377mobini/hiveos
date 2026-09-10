import { useState } from "react";
import { api, setToken } from "../api/client";

interface LoginData {
  user_id: string;
  organization_id: string;
  session: { token: string; expires_at: string };
}

// 00-login.html: ورود بازگشتی — پیام خطا عمداً نمی‌گوید کدام فیلد اشتباه است.
export default function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api<LoginData>("POST", "/auth/login", { username, password });
      setToken(data.session.token);
      onDone();
    } catch (e) {
      const message = e instanceof Error ? e.message : "خطا";
      setError(
        message.includes("قفل")
          ? "ورود موقتاً قفل شد. ۱۵ دقیقه بعد دوباره تلاش کنید."
          : "نام کاربری یا رمز عبور درست نیست. دوباره تلاش کنید.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
      <h1 className="text-lg font-bold">ورود به HiveOS</h1>
      <p className="mt-1 text-sm text-neutral-600">با نام کاربری و رمز عبور حساب خود وارد شوید.</p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <label className="block">
          <span className="text-sm font-semibold">نام کاربری</span>
          <input
            dir="ltr"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-left"
          />
        </label>
        <label className="block">
          <span className="text-sm font-semibold">رمز عبور</span>
          <input
            type="password"
            dir="ltr"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-left"
          />
        </label>
        {error && (
          <div className="rounded-control bg-error-bg p-3 text-sm text-error" role="alert">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-control bg-navy-600 py-2 font-bold text-white disabled:opacity-60"
        >
          {busy ? "..." : "ورود"}
        </button>
      </form>
    </section>
  );
}
