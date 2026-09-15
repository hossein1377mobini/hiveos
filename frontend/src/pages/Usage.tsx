import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Coins, Info, TrendingDown } from "lucide-react";
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

interface WalletState {
  balance: number;
  welcome_credit: number;
  blocked: boolean;
  pending_request: { id: string; amount: number; created_at?: string } | null;
  transactions: WalletTransaction[];
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
