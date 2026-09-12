import { ArrowDownLeft, ArrowUpRight, CircleAlert, Search, Wallet as WalletIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Banner } from "../components/ui/banner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { cn } from "../lib/utils";
import { faDateTime, faNum, norm } from "../utils/format";

// 12-ai-access/02-wallet.html at mockup fidelity: page-head, wallet-hero navy
// card, charge card, transactions card with live search + pagination, zero-
// credit banner (no CTA — review 4). Business adaptation: charging is an
// admin-approved request (T-S3-8), not a gateway payment — the mockup card
// pattern is kept, copy adjusted.
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
    <Banner tone="error" title="اعتبار شما به پایان رسیده است." data-testid="zero-credit-banner">
      برای ادامه گفتگو، حساب خود را شارژ کنید.
    </Banner>
  );
}

const AMOUNTS = [100, 250, 500];
const PAGE_SIZE = 6;

export default function Wallet() {
  const [state, setState] = useState<WalletState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState<number | "custom">(100);
  const [customAmount, setCustomAmount] = useState("");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

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
    const value = amount === "custom" ? Number(customAmount) : amount;
    if (!value || value < 1) return;
    try {
      await api("POST", "/wallet/charge-request", { amount: value, note: note || null });
      setSent(true);
      setState(await api<WalletState>("GET", "/wallet"));
    } catch {
      setError("ثبت درخواست شارژ ناموفق بود.");
    }
  }

  const filtered = useMemo(() => {
    if (!state) return [];
    const q = norm(search);
    if (!q) return state.transactions;
    return state.transactions.filter((t) =>
      norm(faNum(t.amount) + " " + t.amount + " " + t.kind + " " + faDateTime(t.created_at)).includes(q),
    );
  }, [state, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (!state) {
    return <p className="text-sm text-neutral-600">{error ?? "در حال بارگذاری…"}</p>;
  }

  const blocked = state.blocked;

  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-label="کیف پول">
      <div className="flex flex-wrap items-start gap-3.5">
        <div>
          <h1 className="text-[19px] font-extrabold text-neutral-900">کیف پول</h1>
          <p className="mt-[3px] text-[13px] text-neutral-600">اعتبار هوش سازمان و تراکنش‌های شارژ.</p>
        </div>
        <div className="ms-auto flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => document.getElementById("charge-request")?.scrollIntoView({ behavior: "smooth" })}
          >
            شارژ حساب
          </Button>
        </div>
      </div>

      {blocked && (
        <Banner tone="error" title="اعتبار شما به پایان رسیده است." data-testid="zero-credit-banner">
          برای ادامه گفتگو، حساب خود را شارژ کنید.
        </Banner>
      )}

      {/* wallet-hero (mockup §۲۱) */}
      <div className="relative overflow-hidden rounded-[20px] bg-navy-600 px-7 py-[26px] text-white shadow-[0_14px_34px_rgba(43,58,115,0.3)]">
        <span aria-hidden className="absolute -end-[30px] -top-[30px] size-40 rounded-full bg-white/[0.06]" />
        <div className="text-xs font-bold opacity-75">اعتبار فعلی</div>
        <div className="mt-1.5 text-[34px] font-extrabold tracking-[-1px]" data-testid="balance">
          {faNum(state.balance)} <small className="text-sm font-semibold opacity-80">اعتبار</small>
        </div>
        <div className="mt-3.5 flex flex-wrap items-center gap-3.5 text-xs opacity-85">
          <span>واحد: اعتبار هوش سازمان</span>
          <span>اعتبار خوش‌آمدگویی: {faNum(state.welcome_credit)}</span>
        </div>
      </div>

      {state.pending_request ? (
        <Banner tone="warning" title="درخواست شارژ در انتظار تأیید است." data-testid="pending">
          درخواست شارژ {faNum(state.pending_request.amount)} واحدی ثبت شده و در انتظار تأیید مدیر سامانه است.
        </Banner>
      ) : sent ? (
        <Banner tone="success" title="درخواست شارژ ثبت شد.">
          پس از تأیید مدیر سامانه به موجودی اعمال می‌شود.
        </Banner>
      ) : null}

      {error && (
        <Banner tone="error" title="خطا" role="alert" data-testid="wallet-error">
          {error}
        </Banner>
      )}

      {/* شارژ — الگوی «شارژ سریع» ماک‌آپ، با منطق درخواست مدیریتی (US-1203/1204) */}
      <form
        onSubmit={submitChargeRequest}
        id="charge-request"
        className="rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card"
        aria-label="درخواست شارژ"
      >
        <h2 className="text-[15px] font-extrabold text-neutral-900">شارژ حساب</h2>
        <p className="mt-1 text-[12.5px] text-neutral-600">
          مبلغ را انتخاب کنید؛ پس از تأیید مدیر سامانه، اعتبار به کیف پول اضافه می‌شود.
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {AMOUNTS.map((a) => (
            <button
              key={a}
              type="button"
              aria-pressed={amount === a}
              onClick={() => setAmount(a)}
              className={cn(
                "cursor-pointer rounded-[12px] border px-4 py-2.5 text-center transition-colors",
                amount === a
                  ? "border-navy-600 bg-navy-50 text-navy-600"
                  : "border-neutral-200 bg-neutral-0 hover:border-navy-200 hover:bg-navy-50/50",
              )}
            >
              <b className="block text-sm font-extrabold">{faNum(a)}</b>
              <small className="mt-0.5 block text-[11px] text-neutral-400">اعتبار</small>
            </button>
          ))}
          <button
            type="button"
            aria-pressed={amount === "custom"}
            onClick={() => setAmount("custom")}
            className={cn(
              "cursor-pointer rounded-[12px] border px-4 py-2.5 text-center transition-colors",
              amount === "custom"
                ? "border-navy-600 bg-navy-50 text-navy-600"
                : "border-neutral-200 bg-neutral-0 hover:border-navy-200 hover:bg-navy-50/50",
            )}
          >
            <b className="block text-sm font-extrabold">مبلغ دلخواه</b>
            <small className="mt-0.5 block text-[11px] text-neutral-400">تعداد اعتبار</small>
          </button>
        </div>
        {amount === "custom" && (
          <div className="mt-3">
            <label className="mb-1.5 block text-[13px] font-bold text-neutral-900" htmlFor="custom-amount">
              تعداد اعتبار
            </label>
            <Input
              id="custom-amount"
              type="number"
              min={1}
              dir="ltr"
              className="max-w-40 text-left"
              value={customAmount}
              onChange={(e) => setCustomAmount(e.target.value)}
              aria-label="مبلغ دلخواه"
            />
          </div>
        )}
        <div className="mt-3">
          <label className="mb-1.5 block text-[13px] font-bold text-neutral-900" htmlFor="charge-note">
            توضیح (اختیاری)
          </label>
          <Input
            id="charge-note"
            type="text"
            placeholder="مثلاً: شماره پیگیری کارت‌به‌کارت"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="توضیح تراکنش"
          />
        </div>
        <Button type="submit" className="mt-4">
          ثبت درخواست شارژ
        </Button>
      </form>

      {/* تراکنش‌ها (mockup §۲۱ .txn) */}
      <div className="rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
        <h2 className="mb-3 text-[15px] font-extrabold text-neutral-900">تراکنش‌ها</h2>
        <div className="relative mb-3">
          <Search aria-hidden className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
          <Input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            placeholder="جستجو در تراکنش‌ها (مبلغ، تاریخ، نوع)…"
            aria-label="جستجوی تراکنش"
            className="ps-9"
          />
        </div>
        <div>
          {pageItems.map((t) => {
            const isCharge = t.kind === "CHARGE";
            return (
              <div key={t.id} className="flex items-center gap-3 border-b border-neutral-200 py-3 last:border-b-0">
                <span
                  aria-hidden
                  className={cn(
                    "flex size-[34px] shrink-0 items-center justify-center rounded-[10px]",
                    isCharge ? "bg-success-bg text-success" : "border border-neutral-200 bg-neutral-50 text-neutral-600",
                  )}
                >
                  {isCharge ? <ArrowDownLeft className="size-4" /> : <ArrowUpRight className="size-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold text-neutral-900">
                    {isCharge ? "شارژ حساب" : "مصرف گفتگو"}
                  </div>
                  <div className="text-[11.5px] text-neutral-400">{faDateTime(t.created_at)}</div>
                </div>
                <div className={cn("whitespace-nowrap text-[13.5px] font-extrabold", isCharge ? "text-success" : "text-neutral-600")}>
                  {isCharge ? "+" : "−"}
                  {faNum(t.amount)}
                </div>
              </div>
            );
          })}
          {filtered.length === 0 && (
            <div className="px-5 py-10 text-center">
              <span
                aria-hidden
                className="mx-auto mb-3.5 flex size-14 items-center justify-center rounded-[16px] border border-neutral-200 bg-neutral-50 text-neutral-400"
              >
                <WalletIcon className="size-[26px]" />
              </span>
              <h3 className="text-[15px] font-extrabold text-neutral-900">تراکنشی ثبت نشده است</h3>
              <p className="mt-1.5 text-[13px] text-neutral-600">
                {search ? "تراکنشی مطابق جستجو پیدا نشد." : "با اولین گفتگو یا شارژ، تراکنش‌ها اینجا نمایش داده می‌شوند."}
              </p>
            </div>
          )}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-neutral-400">
            نمایش {faNum(pageItems.length)} از {faNum(filtered.length)} تراکنش
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" size="xs" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
              قبلی
            </Button>
            <Button
              variant="secondary"
              size="xs"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
            >
              بعدی
            </Button>
          </div>
        </div>
      </div>

      <p className="flex items-start gap-2 text-[11px] text-neutral-400">
        <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        ثبت درخواست شارژ هزینه‌ای ندارد و پس از تأیید مدیر سامانه اعمال می‌شود.
      </p>
    </section>
  );
}
