import {
  ArrowDownLeft,
  ArrowUpRight,
  CircleAlert,
  Search,
  Wallet as WalletIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ZeroCreditBanner } from "../components/ZeroCreditBanner";
import { RetryNotice } from "../components/ui/retry";
import { Banner } from "../components/ui/banner";
import { LoadingButton } from "../components/ui/button-loading";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Surface } from "../components/ui/surface";
import { statusOf } from "../lib/status";
import { cn } from "../lib/utils";
import { faDate, faDateTime, faNum, norm } from "../utils/format";

/*
 * «کیف پول» and «اشتراک» are one page.
 *
 * PO request 2026-09: the two screens were merged, because the questions they
 * answer are one question - "what can I still spend, and until when". Splitting
 * them meant the credit hero sat on one page and the plan hero on another, and
 * the operator had to reconcile two numbers by memory. The routes are NOT
 * defined here; App.tsx owns the router and redirects /subscription to
 * /wallet, so this file is a plain page component with no links between the
 * halves and no knowledge of a route.
 *
 * 12-ai-access/02-wallet.html and 04-subscription.html at mockup fidelity: the
 * wallet hero, charge card and transactions card keep their patterns, and the
 * subscription hero + «اشتراک و اعتبار» explainer rows are folded in as their
 * own sections. Business adaptation unchanged: charging is an admin-approved
 * request (T-S3-8), not a gateway payment, and the plan is granted/extended by
 * the System Administrator (US-1207).
 */

/**
 * Consumption totals from backend/backend/wallet.py:usage_totals - the exact
 * key set that function returns. No cost_credits: the endpoint does not send one.
 */
interface UsageTotals {
  executions: number;
  tokens_in: number;
  tokens_out: number;
  cached_tokens: number;
  reasoning_tokens: number;
  cost_usd: number;
}

/**
 * The cost basis backend/backend/wallet.py:cost_basis_for writes onto every
 * DEDUCTION (wallet_transactions.cost_basis). `rate` is "avalai_catalog" when
 * AvalAI's public catalogue priced the run and "admin_fallback" when it could
 * not; `reason` says why the fallback happened. The USD figure is null on the
 * fallback path, so a fallback charge has no exact dollar amount - only its
 * credits - and the UI must say so instead of printing a fake number.
 */
interface CostBasis {
  rate?: string | null;
  source?: string | null;
  reason?: string | null;
  known?: boolean;
  credits?: number | null;
  credits_per_usd?: number | null;
  fallback_credit_per_1000_tokens_out?: number | null;
  model?: string | null;
  catalog_url?: string | null;
  pricing?: Record<string, number | null> | null;
}

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
    cost_usd?: number | null;
    cost_basis?: CostBasis | null;
  }>;
  /** Organisation-wide totals (wallet.py:get_wallet_state "usage"). */
  usage?: UsageTotals | null;
  /** The caller's own totals ("my_usage"). */
  my_usage?: UsageTotals | null;
}

interface SubscriptionState {
  plan: string;
  expires_at: string | null;
  expired: boolean;
}

const AMOUNTS = [100, 250, 500];
const PAGE_SIZE = 6;

/**
 * Why a cost had to be estimated instead of priced from AvalAI's catalogue.
 * The vocabulary is backend/backend/wallet.py:cost_basis_for's own reason value.
 */
const FALLBACK_REASON_FA: Record<string, string> = {
  catalog_unavailable: "کاتالوگ قیمت AvalAI در دسترس نبود",
  model_not_in_catalog: "این مدل در کاتالوگ AvalAI نیست",
  pricing_missing: "نرخ این مدل در کاتالوگ ثبت نشده است",
  provider_not_avalai: "درگاه فعال، AvalAI نیست",
  endpoint_not_avalai: "نشانی درگاه، AvalAI نیست",
};

/**
 * USD with honest decimals. Intl's default two would render a real $0.0004
 * charge as "$0", which reads as free; sub-cent amounts get six decimals.
 */
function usdText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const usd = Number(value);
  if (usd === 0) return "$" + faNum(0, 4);
  return "$" + faNum(usd, usd < 0.01 ? 6 : 4);
}

/** True when the cost came from the admin fallback rate, not AvalAI's catalogue. */
function isFallbackCost(basis: CostBasis | null | undefined): boolean {
  return (
    basis?.rate === "admin_fallback" ||
    basis?.source === "admin_fallback_rate" ||
    basis?.known === false
  );
}

/**
 * The sentence that separates an exact AvalAI-priced cost from an estimate.
 * Shown next to any fallback-derived charge so the two never look alike.
 */
function fallbackCaveat(basis: CostBasis | null | undefined): string {
  const reason = basis?.reason ? FALLBACK_REASON_FA[basis.reason] : undefined;
  return reason
    ? "برآوردی — نرخ پشتیبان (" + reason + ")"
    : "برآوردی — نرخ پشتیبان";
}

/** Cached tokens live inside tokens_in; a cached one is priced at its own rate. */
function freshInputTokens(usage: UsageTotals): number {
  return Math.max(0, usage.tokens_in - usage.cached_tokens);
}

/**
 * One consumption summary block: the three token classes AvalAI prices, plus
 * the resulting dollar cost. Rendered for the organisation total and for the
 * caller's own total, because the PO asked for both and the difference matters.
 */
function UsageBreakdown({ label, usage }: { label: string; usage: UsageTotals }) {
  return (
    <div className="rounded-control border border-border bg-secondary p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-caption font-bold text-foreground">{label}</span>
        <span className="text-micro text-muted-foreground">
          <span data-numeric>{faNum(usage.executions)}</span> اجرا
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2">
        <div>
          <dt className="text-micro text-muted-foreground">ورودی تازه</dt>
          <dd className="text-body font-bold" data-numeric>
            {faNum(freshInputTokens(usage))}
          </dd>
        </div>
        <div>
          <dt className="text-micro text-muted-foreground">ورودی کش‌شده</dt>
          <dd className="text-body font-bold text-primary" data-numeric>
            {faNum(usage.cached_tokens)}
          </dd>
        </div>
        <div>
          <dt className="text-micro text-muted-foreground">خروجی</dt>
          <dd className="text-body font-bold" data-numeric>
            {faNum(usage.tokens_out)}
          </dd>
        </div>
      </dl>
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-2 border-t border-border pt-3">
        <span className="text-micro text-muted-foreground">هزینه (دلار)</span>
        <span className="text-caption font-bold" dir="ltr" data-numeric>
          {usdText(usage.cost_usd)}
        </span>
      </div>
    </div>
  );
}

export default function WalletPage() {
  const [state, setState] = useState<WalletState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState<number | "custom">(100);
  const [customAmount, setCustomAmount] = useState("");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [sending, setSending] = useState(false);

  const [sub, setSub] = useState<SubscriptionState | null>(null);
  const [subError, setSubError] = useState<string | null>(null);
  /**
   * When the current subscription answer arrived, so "days remaining" is stable
   * per response: Date.now() during render is impure and two renders of the same
   * data would report different remaining days.
   */
  const [loadedAt, setLoadedAt] = useState<number | null>(null);

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

  // The two halves load independently and report independently: a wallet that
  // fails must not blank the plan, and vice versa. Both endpoints are the ones
  // the two pages called before the merge.
  const loadSubscription = useCallback(async () => {
    setSubError(null);
    try {
      const s = await api<{ subscription: SubscriptionState }>("GET", "/auth/onboarding-status");
      setSub(s.subscription);
      setLoadedAt(Date.now());
    } catch (e) {
      setSub(null);
      setLoadedAt(null);
      setSubError(e instanceof Error ? e.message : "دریافت وضعیت اشتراک ناموفق بود.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadSubscription();
  }, [loadSubscription]);

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

  const daysLeft =
    sub?.expires_at && loadedAt
      ? Math.max(0, Math.ceil((new Date(sub.expires_at).getTime() - loadedAt) / 86_400_000))
      : null;
  // Through the shared registry, not a local two-entry map. The page used to
  // render the raw API value ("annual") for every plan it did not know, while
  // every other surface in the product showed the Persian label. [B7]
  const planFa = sub ? statusOf("plan", sub.plan).label : "";

  return (
    <section className="mx-auto max-w-3xl space-y-5" aria-label="کیف پول و اشتراک">
      {/*
        The page's own title. SharedProvider (App.tsx) does not give the
        authenticated shell a heading, so this section owns the level-one
        heading the axe rule page-has-heading-one asks for - and the shell's
        breadcrumb stays a label rather than a competing title.
      */}
      <div>
        <h1 className="text-title text-foreground">کیف پول و اشتراک</h1>
        <p className="mt-[3px] text-caption text-muted-foreground">
          اعتبار هوش سازمان، تراکنش‌های شارژ و دوره‌ی اشتراک — همه در یک صفحه.
        </p>
      </div>

      <ZeroCreditBanner visible={state?.blocked ?? false} />

      {/*
        — اعتبار و شارژ —
        The section is named for what it holds, not "کیف پول": the page title
        already says that, and a section repeating the page's own name makes two
        headings match it - which is exactly the ambiguity a caller looking up
        "the wallet heading" then has to resolve.
      */}
      <section className="space-y-4" aria-labelledby="wallet-credit-heading">
        <h2 id="wallet-credit-heading" className="text-heading text-foreground">
          اعتبار و شارژ
        </h2>

        {!state && error && (
          <RetryNotice message={error} onRetry={() => void load()} testId="wallet-retry" />
        )}
        {!state && !error && <p className="text-body text-muted-foreground">در حال بارگذاری…</p>}

        {state && (
          <>
            {error && (
              <Banner tone="error" title="خطا" role="alert" data-testid="wallet-error">
                {error}
              </Banner>
            )}

            {/* wallet-hero (mockup §۲۱) */}
            <div className="relative overflow-hidden rounded-card bg-primary px-7 py-[26px] text-primary-foreground shadow-pop">
              <span aria-hidden className="absolute -end-[30px] -top-[30px] size-40 rounded-full bg-white/[0.06]" />
              <div className="text-caption font-bold opacity-75">اعتبار فعلی</div>
              <div className="mt-1.5 text-display font-bold" data-testid="balance">
                {faNum(state.balance)}{" "}
                <small className="text-body font-semibold opacity-80">اعتبار</small>
              </div>
              <div className="mt-3.5 flex flex-wrap items-center gap-3.5 text-caption opacity-85">
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

            {/*
              Consumption, broken down by the three token classes AvalAI bills.
              The PO's «میزان مصرف هر کاربر» is my_usage; the organisation total
              sits beside it so an operator can see the caller's share. A cached
              token is priced below a fresh input token, which is why the cached
              count is called out rather than folded into "ورودی".
            */}
            {(state.usage || state.my_usage) && (
              <Surface className="p-6" data-testid="wallet-usage-summary">
                <h3 className="text-subheading text-foreground">مصرف به تفکیک نوع توکن</h3>
                <p className="mt-1 text-caption text-muted-foreground">
                  هزینه بر پایهٔ نرخ‌های عمومی AvalAI و با فرمول خودش برای هر سه دستهٔ توکن
                  (ورودی تازه، ورودی کش‌شده، خروجی) محاسبه می‌شود؛ توکن کش‌شده ارزان‌تر از توکن
                  ورودی تازه است.
                </p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {state.usage && <UsageBreakdown label="مصرف سازمان" usage={state.usage} />}
                  {state.my_usage && <UsageBreakdown label="مصرف من" usage={state.my_usage} />}
                </div>
              </Surface>
            )}

            {/* شارژ — الگوی «شارژ سریع» ماک‌آپ، با منطق درخواست مدیریتی (US-1203/1204) */}
            <form
              onSubmit={submitChargeRequest}
              id="charge-request"
              className="rounded-card border border-border bg-card p-6 shadow-card"
              aria-label="درخواست شارژ"
            >
              <h3 className="text-subheading text-foreground">شارژ حساب</h3>
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
                      "cursor-pointer rounded-control border px-4 py-2.5 text-center transition-colors",
                      amount === a
                        ? "border-primary bg-accent text-primary"
                        : "border-border bg-card hover:border-primary/40 hover:bg-accent/50",
                    )}
                  >
                    <b className="block text-body font-bold">{faNum(a)}</b>
                    <small className="mt-0.5 block text-micro text-muted-foreground">اعتبار</small>
                  </button>
                ))}
                <button
                  type="button"
                  aria-pressed={amount === "custom"}
                  onClick={() => setAmount("custom")}
                  className={cn(
                    "cursor-pointer rounded-control border px-4 py-2.5 text-center transition-colors",
                    amount === "custom"
                      ? "border-primary bg-accent text-primary"
                      : "border-border bg-card hover:border-primary/40 hover:bg-accent/50",
                  )}
                >
                  <b className="block text-body font-bold">مبلغ دلخواه</b>
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

            <p className="flex items-start gap-2 text-micro text-muted-foreground">
              <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              ثبت درخواست شارژ هزینه‌ای ندارد و پس از تأیید مدیر سامانه اعمال می‌شود.
            </p>
          </>
        )}
      </section>

      {/* — اشتراک — */}
      <section className="space-y-4" aria-labelledby="wallet-plan-heading">
        <h2 id="wallet-plan-heading" className="text-heading text-foreground">
          اشتراک
        </h2>

        {!sub && subError && (
          <RetryNotice
            message={subError}
            onRetry={() => void loadSubscription()}
            testId="subscription-retry"
          />
        )}
        {!sub && !subError && <p className="text-body text-muted-foreground">در حال بارگذاری…</p>}

        {sub && (
          <>
            {sub.expired && (
              <Banner tone="error" title="اشتراک شما منقضی شده است." data-testid="sub-expired-banner">
                اجرای هوش سازمان متوقف است؛ اعتبار باقی‌مانده کیف پول شما محفوظ می‌ماند. برای ادامه، از مدیر سامانه تمدید بخواهید.
              </Banner>
            )}

            {/* وضعیت اشتراک — الگوی wallet-hero (mockup §۲۱) */}
            <div className="relative overflow-hidden rounded-card bg-primary px-7 py-[26px] text-primary-foreground shadow-pop">
              <span aria-hidden className="absolute -end-[30px] -top-[30px] size-40 rounded-full bg-white/[0.06]" />
              <div className="text-caption font-bold opacity-75">وضعیت اشتراک</div>
              <div className="mt-1.5 text-title font-bold" data-testid="plan">
                {sub.expired ? "منقضی شده" : `فعال — بسته‌ی ${planFa}`}
              </div>
              <div className="mt-2 text-caption opacity-85" data-testid="expiry">
                {sub.expires_at
                  ? `پایان دوره: ${faDate(sub.expires_at)}${daysLeft && daysLeft > 0 ? ` · ${faNum(daysLeft)} روز باقی‌مانده` : ""}`
                  : "بدون انقضا"}
              </div>
            </div>

            <p className="text-caption text-muted-foreground">
              تمدید و تغییر پلن توسط مدیر سامانه در پنل مدیریت انجام می‌شود.
            </p>

            {/* اشتراک و اعتبار — تفاوت‌ها (setting-row, mockup) */}
            <Surface className="p-6">
              <h3 className="mb-3 text-subheading text-foreground">اشتراک و اعتبار — تفاوت‌ها</h3>
              <div className="border-b border-border py-3.5 last:border-b-0">
                <div className="text-caption font-bold text-foreground">اشتراک فعال</div>
                <div className="mt-0.5 max-w-[520px] text-caption text-muted-foreground">
                  دسترسی به خود برنامه را تأمین می‌کند؛ بدون آن، اجرای هوش سازمان متوقف است.
                </div>
              </div>
              <div className="border-b border-border py-3.5 last:border-b-0">
                <div className="text-caption font-bold text-foreground">اعتبار بسته‌ی اشتراک</div>
                <div className="mt-0.5 max-w-[520px] text-caption text-muted-foreground">
                  با خرید/تمدید، یک‌جا به کیف پول اضافه می‌شود و با مصرف کسر می‌شود.
                </div>
              </div>
              <div className="border-b border-border py-3.5 last:border-b-0">
                <div className="text-caption font-bold text-foreground">اعتبار مکمل</div>
                <div className="mt-0.5 max-w-[520px] text-caption text-muted-foreground">
                  در هر لحظه از دوره قابل درخواست است — از «کیف پول ← شارژ حساب» در همین صفحه.
                </div>
              </div>
              <div className="border-b border-border py-3.5 last:border-b-0">
                <div className="text-caption font-bold text-foreground">پایان دوره</div>
                <div className="mt-0.5 max-w-[520px] text-caption text-muted-foreground">
                  اعتبار باقی‌مانده حفظ می‌شود؛ تا تمدید اشتراک، اجرای هوش سازمان متوقف می‌ماند.
                </div>
              </div>
              <div className="py-3.5 last:border-b-0">
                <div className="text-caption font-bold text-foreground">دوره آزمایشی (سازمان جدید)</div>
                <div className="mt-0.5 max-w-[520px] text-caption text-muted-foreground">
                  با اعتبار خوش‌آمد — بدون نیاز به اشتراک. مدت و مقدار اعتبار از پنل ادمین تعیین می‌شود.
                </div>
              </div>
            </Surface>
          </>
        )}
      </section>

      {/* — تراکنش‌ها — */}
      <section className="space-y-4" aria-labelledby="wallet-tx-heading">
        <h2 id="wallet-tx-heading" className="text-heading text-foreground">
          تراکنش‌ها
        </h2>
        <Surface className="p-6">
          {/*
            The surface used to carry its own heading. It is now the section's,
            one level up, so the card does not repeat the word directly below
            it - and the "no transactions" note stays an h3, which is what
            keeps the heading order descending.
          */}
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
                      "flex size-[34px] shrink-0 items-center justify-center rounded-control",
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
                    {/*
                      The real, provider-derived cost of this deduction. A cost
                      priced from AvalAI's live catalogue prints its USD figure;
                      a fallback-derived one has no exact USD (cost_usd is null)
                      and says so instead of showing a number it does not have.
                    */}
                    {!isCharge && (t.cost_usd != null || isFallbackCost(t.cost_basis)) && (
                      <div
                        className="mt-0.5 text-micro text-muted-foreground"
                        data-testid={"tx-cost-" + t.id}
                      >
                        {t.cost_usd != null && (
                          <span dir="ltr" data-numeric>
                            {usdText(t.cost_usd)}
                          </span>
                        )}
                        {t.cost_usd != null && isFallbackCost(t.cost_basis) && " · "}
                        {isFallbackCost(t.cost_basis) && (
                          <span className="font-bold text-warning">
                            {fallbackCaveat(t.cost_basis)}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className={cn("whitespace-nowrap text-caption font-bold", isCharge ? "text-success" : "text-muted-foreground")}>
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
                  className="mx-auto mb-3.5 flex size-14 items-center justify-center rounded-card border border-border bg-secondary text-muted-foreground"
                >
                  <WalletIcon className="size-[26px]" />
                </span>
                <h3 className="text-subheading text-foreground">تراکنشی ثبت نشده است</h3>
                <p className="mt-1.5 text-caption text-muted-foreground">
                  {search ? "تراکنشی مطابق جستجو پیدا نشد." : "با اولین گفتگو یا شارژ، تراکنش‌ها اینجا نمایش داده می‌شوند."}
                </p>
              </div>
            )}
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-caption text-muted-foreground">
              نمایش {faNum(pageItems.length)} از {faNum(filtered.length)} تراکنش
            </span>
            <div className="flex gap-2">
              <LoadingButton variant="secondary" size="sm" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
                قبلی
              </LoadingButton>
              <LoadingButton
                variant="secondary"
                size="sm"
                disabled={safePage >= pageCount - 1}
                onClick={() => setPage(safePage + 1)}
              >
                بعدی
              </LoadingButton>
            </div>
          </div>
        </Surface>
      </section>
    </section>
  );
}
