import { useEffect, useState } from "react";
import { api } from "../api/client";

// 12-ai-access/wallet.html (design-system v0.4.0): balance card, charge
// request (T-S3-8 zero-open loop), zero-credit banner, transactions.
interface WalletState {
  balance: number;
  welcome_credit: number;
  blocked: boolean;
  pending_request: { id: string; amount: number } | null;
  transactions: Array<{
    id: string;
    kind: string;
    amount: number;
    balance_after: number;
    created_at: string;
  }>;
}

export function ZeroCreditBanner({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div
      role="alert"
      className="rounded-card border border-red-200 bg-red-50 p-4 text-sm text-red-800"
      data-testid="zero-credit-banner"
    >
      اعتبار شما تمام شده است. برای ادامهٔ گفتگو، درخواست شارژ ثبت کنید.
    </div>
  );
}

export default function Wallet() {
  const [state, setState] = useState<WalletState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState(100);
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setState(await api<WalletState>("GET", "/wallet"));
      } catch {
        setError("دریافت وضعیت کیف پول ناموفق بود.");
      }
    })();
  }, []);

  async function submitChargeRequest(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("POST", "/wallet/charge-request", { amount, note: note || null });
      setSent(true);
      setState(await api<WalletState>("GET", "/wallet"));
    } catch {
      setError("ثبت درخواست شارژ ناموفق بود.");
    }
  }

  if (!state) {
    return <p className="text-sm text-neutral-600">{error ?? "در حال بارگذاری…"}</p>;
  }

  return (
    <section className="mx-auto max-w-2xl space-y-4" aria-label="کیف پول">
      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
        <p className="text-sm text-neutral-600">موجودی اعتبار</p>
        <p className="mt-1 text-3xl font-bold" data-testid="balance">
          {state.balance}
        </p>
      </div>

      <ZeroCreditBanner visible={state.blocked} />

      {state.pending_request ? (
        <p className="rounded-card bg-amber-50 p-3 text-sm text-amber-800" data-testid="pending">
          درخواست شارژ {state.pending_request.amount} واحدی در انتظار تأیید مدیر سامانه است.
        </p>
      ) : sent ? (
        <p className="rounded-card bg-green-50 p-3 text-sm text-green-800">
          درخواست شارژ ثبت شد؛ پس از تأیید مدیر اعمال می‌شود.
        </p>
      ) : null}

      <form
        onSubmit={submitChargeRequest}
        className="rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card"
        aria-label="درخواست شارژ"
      >
        <h2 className="text-sm font-bold">درخواست شارژ</h2>
        <div className="mt-3 flex gap-2">
          {[100, 250, 500].map((a) => (
            <button
              key={a}
              type="button"
              onClick={() => setAmount(a)}
              className={
                "rounded-control border px-4 py-2 text-sm " +
                (amount === a ? "border-navy-600 bg-navy-50 font-bold" : "border-neutral-200")
              }
            >
              {a}
            </button>
          ))}
          <input
            type="number"
            min={1}
            aria-label="مبلغ دلخواه"
            className="w-28 rounded-control border border-neutral-200 px-3 py-2 text-sm"
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
        </div>
        <input
          type="text"
          aria-label="توضیح تراکنش"
          placeholder="مثلاً: شماره پیگیری کارت‌به‌کارت"
          className="mt-3 w-full rounded-control border border-neutral-200 px-3 py-2 text-sm"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          type="submit"
          className="mt-3 rounded-control bg-navy-600 px-4 py-2 text-sm font-bold text-white"
        >
          ثبت درخواست
        </button>
      </form>

      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
        <h2 className="text-sm font-bold">تراکنش‌ها</h2>
        <ul className="mt-2 divide-y divide-neutral-100 text-sm">
          {state.transactions.map((t) => (
            <li key={t.id} className="flex justify-between py-2">
              <span>{t.kind === "CHARGE" ? "شارژ" : "مصرف"}</span>
              <span dir="ltr">
                {t.kind === "CHARGE" ? "+" : "-"}
                {t.amount}
              </span>
            </li>
          ))}
          {state.transactions.length === 0 && (
            <li className="py-2 text-neutral-500">تراکنشی ثبت نشده است.</li>
          )}
        </ul>
      </div>
    </section>
  );
}
