import { ArrowDownLeft, ArrowUpRight, CircleAlert, Search, Wallet as WalletIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ZeroCreditBanner } from "../components/ZeroCreditBanner";
import { RetryNotice } from "../components/ui/retry";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { Input } from "../components/ui/input";
import { cn } from "../lib/utils";
import { faDateTime, faNum, norm } from "../utils/format";
import { Label } from "../components/ui/label";
import { Surface } from "../components/ui/surface";

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
  const [sending, setSending] = useState(false);

  // PO request: a failed load shows the server's own Persian explanation plus
  // a «تلاش مجدد» button, instead of a dead "..." screen.
  const load = useCallback(async () => {
    setError(null);
    try {
      setState(await api<WalletState>("GET", "/wallet"));
    } catch (e) {
      setState(null);
      setError(e instanceof Error ? e.message : "دریافت وضعیت کیف پول ناموفق بود.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitChargeRequest(e: React.FormEvent) {
    e.preventDefault();
    // D7: without a guard a double click files the same charge request twice.
    if (sending) return;
    setError(null);
    const value = amount === "custom" ? Number(customAmount) : amount;
    if (!value || value < 1) return;
    setSending(true);
    setSent(false);
    try {
      await api("POST", "/wallet/charge-request", { amount: value, note: note || null });
      setSent(true);
      setState(await api<WalletState>("GET", "/wallet"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "ثبت درخواست شارژ ناموفق بود.");
    } finally {
      setSending(false);
    }
  }

  const filtered = useMemo(() => {
    if (!state) return [];
    // D7: a payload without 'transactions' used to throw on the next line and
    // white-screen the page.
    const transactions = state.transactions ?? [];
    const q = norm(search);
    if (!q) return transactions;
    return transactions.filter((t) =>
      norm(faNum(t.amount) + " " + t.amount + " " + t.kind + " " + faDateTime(t.created_at)).includes(q),
    );
  }, [state, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (!state) {
    if (error) {
      return <RetryNotice message={error} onRetry={() => void load()} testId="wallet-retry" />;
    }
    return <p className="text-sm text-muted-foreground">در حال بارگذاری…</p>;
  }

  const blocked = state.blocked;

  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-label="کیف پول">
      <div className="flex flex-wrap items-start gap-3.5">
        <div>
          <h1 className="text-heading font-extrabold text-foreground">کیف پول</h1>
          <p className="mt-[3px] text-caption text-muted-foreground">اعتبار هوش سازمان و تراکنش‌های شارژ.</p>
        </div>
        <div className="ms-auto flex items-center gap-2">
          <LoadingButton
            size="sm"
            onClick={() => document.getElementById("charge-request")?.scrollIntoView({ behavior: "smooth" })}
          >
            شارژ حساب
          </LoadingButton>
        </div>
      </div>

      <ZeroCreditBanner visible={blocked} />

      {/* wallet-hero (mockup §۲۱) */}
      <div className="relative overflow-hidden rounded-[20px] bg-primary px-7 py-[26px] text-primary-foreground shadow-[0_14px_34px_rgba(43,58,115,0.3)]">
        <span aria-hidden className="absolute -end-[30px] -top-[30px] size-40 rounded-full bg-white/[0.06]" />
        <div className="text-xs font-bold opacity-75">اعتبار فعلی</div>
        <div className="mt-1.5 text-display font-extrabold tracking-[-1px]" data-testid="balance">
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
        className="rounded-card border border-border bg-card p-6 shadow-card"
        aria-label="درخواست شارژ"
      >
        <h2 className="text-body font-extrabold text-foreground">شارژ حساب</h2>
        <p className="mt-1 text-caption text-muted-foreground">
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
                  ? "border-primary bg-accent text-primary"
                  : "border-border bg-card hover:border-primary/40 hover:bg-accent/50",
              )}
            >
              <b className="block text-sm font-extrabold">{faNum(a)}</b>
              <small className="mt-0.5 block text-micro text-muted-foreground">اعتبار</small>
            </button>
          ))}
          <button
            type="button"
            aria-pressed={amount === "custom"}
            onClick={() => setAmount("custom")}
            className={cn(
              "cursor-pointer rounded-[12px] border px-4 py-2.5 text-center transition-colors",
              amount === "custom"
                ? "border-primary bg-accent text-primary"
                : "border-border bg-card hover:border-primary/40 hover:bg-accent/50",
            )}
          >
            <b className="block text-sm font-extrabold">مبلغ دلخواه</b>
            <small className="mt-0.5 block text-micro text-muted-foreground">تعداد اعتبار</small>
          </button>
        </div>
        {amount === "custom" && (
          <div className="mt-3">
            <Label className="mb-1.5 text-caption font-bold text-foreground" htmlFor="custom-amount">
              تعداد اعتبار
            </Label>
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
          <Label className="mb-1.5 text-caption font-bold text-foreground" htmlFor="charge-note">
            توضیح (اختیاری)
          </Label>
          <Input
            id="charge-note"
            type="text"
            placeholder="مثلاً: شماره پیگیری کارت‌به‌کارت"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="توضیح تراکنش"
          />
        </div>
        <LoadingButton type="submit" className="mt-4" loading={sending} disabled={sending}>
          ثبت درخواست شارژ
        </LoadingButton>
      </form>

      {/* تراکنش‌ها (mockup §۲۱ .txn) */}
      <Surface className="p-6">
        <h2 className="mb-3 text-body font-extrabold text-foreground">تراکنش‌ها</h2>
        <div className="relative mb-3">
          <Search aria-hidden className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
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
              <div key={t.id} className="flex items-center gap-3 border-b border-border py-3 last:border-b-0">
                <span
                  aria-hidden
                  className={cn(
                    "flex size-[34px] shrink-0 items-center justify-center rounded-[10px]",
                    isCharge ? "bg-success-bg text-success" : "border border-border bg-secondary text-muted-foreground",
                  )}
                >
                  {isCharge ? <ArrowDownLeft className="size-4" /> : <ArrowUpRight className="size-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-caption font-bold text-foreground">
                    {isCharge ? "شارژ حساب" : "مصرف گفتگو"}
                  </div>
                  <div className="text-micro text-muted-foreground">{faDateTime(t.created_at)}</div>
                </div>
                <div className={cn("whitespace-nowrap text-caption font-extrabold", isCharge ? "text-success" : "text-muted-foreground")}>
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
                className="mx-auto mb-3.5 flex size-14 items-center justify-center rounded-[16px] border border-border bg-secondary text-muted-foreground"
              >
                <WalletIcon className="size-[26px]" />
              </span>
              <h3 className="text-body font-extrabold text-foreground">تراکنشی ثبت نشده است</h3>
              <p className="mt-1.5 text-caption text-muted-foreground">
                {search ? "تراکنشی مطابق جستجو پیدا نشد." : "با اولین گفتگو یا شارژ، تراکنش‌ها اینجا نمایش داده می‌شوند."}
              </p>
            </div>
          )}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            نمایش {faNum(pageItems.length)} از {faNum(filtered.length)} تراکنش
          </span>
          <div className="flex gap-2">
            <LoadingButton variant="secondary" size="xs" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
              قبلی
            </LoadingButton>
            <LoadingButton
              variant="secondary"
              size="xs"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
            >
              بعدی
            </LoadingButton>
          </div>
        </div>
      </Surface>

      <p className="flex items-start gap-2 text-micro text-muted-foreground">
        <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        ثبت درخواست شارژ هزینه‌ای ندارد و پس از تأیید مدیر سامانه اعمال می‌شود.
      </p>
    </section>
  );
}