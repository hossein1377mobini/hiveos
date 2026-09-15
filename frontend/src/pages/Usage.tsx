import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Coins, Info, TrendingDown, UserRound } from "lucide-react";
import { api } from "../api/client";
import { Banner } from "../components/ui/banner";
import { RetryNotice } from "../components/ui/retry";
// Surface is the product's official page primitive (components/ui/surface.tsx):
// it is Card with the elevation token, radius, border and padding applied once.
// This page used to import Card directly, which is why it did not look like its
// siblings - every other page in the app and the admin panel uses Surface.
import {
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Surface,
} from "../components/ui/surface";
import { Progress } from "../components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { faDateTime, faNum } from "../utils/format";

// «اعتبار و مصرف» (PO request 2026-09-13). This page used to be a placeholder
// telling the user the report would arrive in a later sprint - while the very
// same data was already sitting in /wallet. The PO's model is manual top-up:
// a user files a request, the System Admin approves it. That only works if the
// user can see what they have, what they spent and what is still pending, so
// none of those three is hidden behind a second screen.

interface WalletTransaction {
  id: string;
  kind: string;
  amount: number;
  balance_after: number;
  execution_id: string | null;
  created_at: string;
}

/**
 * Consumption totals, exactly as backend/backend/wallet.py:usage_totals returns
 * them: {executions, tokens_in, tokens_out, cached_tokens, reasoning_tokens,
 * cost_usd}. There is deliberately no cost_credits here - usage_totals does not
 * send one, and inventing it would be a lie about the arithmetic.
 */
interface UsageTotals {
  executions: number;
  tokens_in: number;
  tokens_out: number;
  cached_tokens: number;
  reasoning_tokens: number;
  cost_usd: number;
}

interface WalletState {
  balance: number;
  welcome_credit: number;
  blocked: boolean;
  pending_request: { id: string; amount: number; created_at?: string } | null;
  transactions: WalletTransaction[];
  /** Organisation-wide totals (wallet.py:get_wallet_state "usage"). */
  usage?: UsageTotals | null;
  /** The caller's own totals ("my_usage") - the PO's «میزان مصرف هر کاربر». */
  my_usage?: UsageTotals | null;
}

/**
 * USD with enough decimals to stay honest.
 *
 * Intl's default (2) renders a real $0.0004 charge as "$0", which reads as
 * "free" - the one thing it was not. Anything under a cent gets six decimals,
 * so the smallest billable amount still shows a non-zero number.
 */
function usdText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const usd = Number(value);
  if (usd === 0) return "$" + faNum(0, 4);
  return "$" + faNum(usd, usd < 0.01 ? 6 : 4);
}

/**
 * AvalAI prices a cached input token at its own (usually much lower) rate, so
 * the fresh part of the prompt is tokens_in - cached_tokens. cached_tokens sits
 * INSIDE tokens_in in the provider's usage object, so showing both numbers
 * unadjusted would double-count the cached ones.
 */
function freshInputTokens(usage: UsageTotals): number {
  return Math.max(0, usage.tokens_in - usage.cached_tokens);
}

/** Transaction kinds as the backend writes them (wallet.py). */
const KIND_FA: Record<string, { label: string; spend: boolean }> = {
  CHARGE: { label: "شارژ", spend: false },
  DEDUCTION: { label: "مصرف", spend: true },
  REFUND: { label: "بازگشت اعتبار", spend: false },
  ADJUSTMENT: { label: "اصلاح دستی", spend: false },
  WELCOME: { label: "اعتبار خوش‌آمدگویی", spend: false },
};

const kindOf = (kind: string) => KIND_FA[kind] ?? { label: kind, spend: true };

export default function Usage() {
  const [state, setState] = useState<WalletState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setState(await api<WalletState>("GET", "/wallet"));
    } catch (e) {
      setState(null);
      setError(e instanceof Error ? e.message : "دریافت گزارش مصرف ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Charges and spends are separated because the PO's question is "am I
  // burning credit faster than I top it up", which one signed total hides.
  const totals = useMemo(() => {
    const rows = state?.transactions ?? [];
    let charged = 0;
    let spent = 0;
    for (const row of rows) {
      const kind = kindOf(row.kind);
      // The sign on amount is authoritative; kind only supplies the label.
      if (kind.spend || row.amount < 0) spent += Math.abs(row.amount);
      else charged += Math.abs(row.amount);
    }
    return { charged, spent };
  }, [state]);

  // The wallet endpoint returns the newest 20 rows, so this is a share of the
  // recent window rather than of all time - the copy on the card says so.
  const flow = totals.charged + totals.spent;
  const share = flow > 0 ? Math.round((totals.spent / flow) * 100) : 0;

  if (!state) {
    if (error) return <RetryNotice message={error} onRetry={() => void load()} testId="usage-retry" />;
    return <p className="text-body text-muted-foreground">در حال بارگذاری…</p>;
  }

  const my = state.my_usage ?? null;

  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-label="اعتبار و مصرف">
      <div>
        <h1 className="text-title">اعتبار و مصرف</h1>
        <p className="mt-[3px] text-caption text-muted-foreground">
          موجودی، مصرف و درخواست‌های شارژ سازمان شما.
        </p>
      </div>

      {state.blocked && (
        <Banner tone="error" title="اعتبار شما به پایان رسیده است." data-testid="usage-zero-banner">
          برای ادامه گفتگو، از صفحهٔ «کیف پول» درخواست شارژ ثبت کنید.
        </Banner>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Surface>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-micro font-bold text-muted-foreground">
              <Coins className="size-3.5" /> اعتبار فعلی
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-display" data-testid="usage-balance">{faNum(state.balance)}</p>
          </CardContent>
        </Surface>
        <Surface>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-micro font-bold text-muted-foreground">
              <ArrowDownLeft className="size-3.5 text-success" /> شارژهای اخیر
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-display text-success" data-testid="usage-charged">{faNum(totals.charged)}</p>
          </CardContent>
        </Surface>
        <Surface>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-micro font-bold text-muted-foreground">
              <ArrowUpRight className="size-3.5 text-error" /> مصرف اخیر
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-display text-error" data-testid="usage-spent">{faNum(totals.spent)}</p>
          </CardContent>
        </Surface>
      </div>

      {my && (
        <Surface data-testid="usage-my-usage">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-body font-bold">
              <UserRound className="size-4" /> مصرف من
            </CardTitle>
            <CardDescription className="text-caption">
              بر پایهٔ <span data-numeric>{faNum(my.executions)}</span> اجرا، با همان سه دسته‌ای که
              AvalAI صورت‌حساب می‌کند: ورودی تازه، ورودی کش‌شده و خروجی — هر کدام با نرخ خودش.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-control border border-border bg-secondary p-3">
                <div className="text-micro text-muted-foreground">ورودی تازه (بدون کش)</div>
                <div className="mt-1 text-heading" data-numeric data-testid="my-usage-input">
                  {faNum(freshInputTokens(my))}
                </div>
                <div className="mt-0.5 text-micro text-muted-foreground">توکن — با نرخ ورودی</div>
              </div>
              <div className="rounded-control border border-border bg-accent p-3">
                <div className="text-micro text-muted-foreground">ورودی کش‌شده</div>
                <div
                  className="mt-1 text-heading text-primary"
                  data-numeric
                  data-testid="my-usage-cached"
                >
                  {faNum(my.cached_tokens)}
                </div>
                <div className="mt-0.5 text-micro text-muted-foreground">
                  توکن — ارزان‌تر از ورودی تازه
                </div>
              </div>
              <div className="rounded-control border border-border bg-secondary p-3">
                <div className="text-micro text-muted-foreground">خروجی مدل</div>
                <div className="mt-1 text-heading" data-numeric data-testid="my-usage-output">
                  {faNum(my.tokens_out)}
                </div>
                <div className="mt-0.5 text-micro text-muted-foreground">توکن — با نرخ خروجی</div>
              </div>
            </div>

            <div className="flex flex-wrap items-baseline justify-between gap-2 border-t border-border pt-3">
              <span className="text-caption text-muted-foreground">هزینهٔ مصرف من (دلار)</span>
              <span className="text-body font-bold" dir="ltr" data-numeric data-testid="my-usage-cost">
                {usdText(my.cost_usd)}
              </span>
            </div>

            <p className="flex items-start gap-1.5 text-caption text-muted-foreground">
              <Info className="mt-0.5 size-3 shrink-0" />
              توکن کش‌شده با نرخ مخصوص خودش و ارزان‌تر از توکن ورودی تازه حساب می‌شود؛ فقط بخش تازهٔ
              پرسش با نرخ کامل ورودی صورت‌حساب می‌شود.
              {my.reasoning_tokens > 0 && (
                <>
                  {" "}
                  از توکن‌های خروجی، <span data-numeric>{faNum(my.reasoning_tokens)}</span> توکن
                  استدلال است که داخل همان خروجی شمرده می‌شود و جداگانه حساب نمی‌شود.
                </>
              )}
            </p>
          </CardContent>
        </Surface>
      )}

      <Surface>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-body font-bold">
            <TrendingDown className="size-4" /> نسبت مصرف به شارژ
          </CardTitle>
          <CardDescription className="flex items-start gap-1.5 text-caption">
            <Info className="mt-0.5 size-3 shrink-0" />
            بر پایهٔ {faNum(state.transactions?.length ?? 0)} تراکنش آخر — نه کل تاریخ حساب.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-body font-bold">{share}٪ از گردش اخیر صرف مصرف شده است.</p>
          {/* role="progressbar" carries no information on its own: a screen
              reader announces "progress bar" with no idea what is progressing.
              The label repeats what the sentence above already states for
              sighted users, so both get the same fact. */}
          <Progress value={share} className="h-2" aria-label="نسبت مصرف به شارژ" />
        </CardContent>
      </Surface>

      {state.pending_request && (
        <Banner tone="warning" title="درخواست شارژ در انتظار تأیید است." data-testid="usage-pending">
          درخواست {faNum(state.pending_request.amount)} واحدی شما ثبت شده است
          {state.pending_request.created_at ? " در " + faDateTime(state.pending_request.created_at) : ""}
          {" و پس از تأیید مدیر سامانه به موجودی اضافه می‌شود."}
        </Banner>
      )}

      {error && (
        <Banner tone="error" title="خطا" role="alert">{error}</Banner>
      )}

      <Surface>
        <CardHeader className="pb-2">
          <CardTitle className="text-body font-bold">تراکنش‌های اخیر</CardTitle>
        </CardHeader>
        <CardContent>
          {state.transactions?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>نوع</TableHead>
                  <TableHead>مبلغ</TableHead>
                  <TableHead>موجودی پس از تراکنش</TableHead>
                  <TableHead>زمان</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {state.transactions.map((row) => {
                  const kind = kindOf(row.kind);
                  const isSpend = kind.spend || row.amount < 0;
                  return (
                    <TableRow key={row.id}>
                      <TableCell className="text-caption">{kind.label}</TableCell>
                      <TableCell className={isSpend ? "font-bold text-error" : "font-bold text-success"}>
                        {(isSpend ? "−" : "+") + faNum(Math.abs(row.amount))}
                      </TableCell>
                      <TableCell>{faNum(row.balance_after)}</TableCell>
                      <TableCell className="text-caption text-muted-foreground">{faDateTime(row.created_at)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <p className="text-caption text-muted-foreground">هنوز تراکنشی ثبت نشده است.</p>
          )}
        </CardContent>
      </Surface>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded-control border px-3 py-1.5 text-caption font-bold hover:bg-muted disabled:opacity-50"
        >
          {loading ? "در حال به‌روزرسانی…" : "به‌روزرسانی"}
        </button>
      </div>
    </section>
  );
}
