import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Cpu, Database, Gauge, HardDrive, MemoryStick, Network, RefreshCw, Server, Sparkles, XCircle } from "lucide-react";
import { persianError } from "../api/errors";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Progress } from "../components/ui/progress";
import { Surface } from "../components/ui/surface";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { adminApi, AdminSessionExpired, Retry } from "./AdminApp";

// Server + AI account monitoring (PO request 2026-09-13). The PO runs this
// product on a machine he does not sit in front of, so the panel has to answer
// "is it healthy" and "is the AI account still funded" without a terminal.
//
// Two rules shape this file: no English ever reaches the PO (the backend's
// developer text stays in the logs), and a number is never more than 60s stale
// while the tab is open - a monitoring page showing page-load data is a lie.

const faNum = (value: number | null | undefined, digits = 0): string => {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fa-IR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

const bytes = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return faNum(size, unit === 0 ? 0 : 1) + " " + units[unit];
};

const duration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return faNum(days) + " روز و " + faNum(hours) + " ساعت";
  if (hours > 0) return faNum(hours) + " ساعت و " + faNum(minutes) + " دقیقه";
  return faNum(minutes) + " دقیقه";
};

const rate = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  return bytes(value) + "/ث";
};

/** Three-state severity, matching the backend's green/degraded/red contract. */
type Tone = "ok" | "warn" | "bad";

const TONE_CLASS: Record<Tone, string> = {
  ok: "text-success",
  warn: "text-warning",
  bad: "text-error",
};

const TONE_BG: Record<Tone, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  bad: "bg-error",
};

/** Thresholds are deliberately conservative: the PO should learn about a
 * filling disk long before it becomes an outage. */
function toneForPercent(percent: number | null, warn: number, bad: number): Tone {
  if (percent === null) return "ok";
  if (percent >= bad) return "bad";
  if (percent >= warn) return "warn";
  return "ok";
}

const GAUGE_WARN = 75;
const GAUGE_BAD = 90;

interface GaugeProps {
  title: string;
  icon: React.ReactNode;
  percent: number | null;
  detail: string;
  hint?: string;
  history: number[];
}

/** A gauge keeps the last few readings so a spike is visible as a trend
 * instead of a single number the PO has to interpret from memory. */
function Gauge2({ title, icon, percent, detail, hint, history }: GaugeProps) {
  const tone = toneForPercent(percent, GAUGE_WARN, GAUGE_BAD);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-bold">
          <span className={TONE_CLASS[tone]}>{icon}</span>
          {title}
        </CardTitle>
        <CardDescription className="text-xs" data-testid={`gauge-detail-${title}`}>
          {detail}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-baseline gap-2">
          <span className={`text-2xl font-black ${TONE_CLASS[tone]}`} data-testid={`gauge-value-${title}`}>
            {percent === null ? "—" : faNum(percent, 1) + "٪"}
          </span>
        </div>
        <Progress
          value={percent ?? 0}
          className={`h-2 ${percent !== null && percent >= GAUGE_BAD ? "[&>[data-slot=progress-indicator]]:bg-error" : percent !== null && percent >= GAUGE_WARN ? "[&>[data-slot=progress-indicator]]:bg-warning" : ""}`}
        />
        {history.length > 1 && (
          <div className="flex h-6 items-end gap-0.5" aria-hidden="true">
            {history.map((point, index) => (
              <div
                key={index}
                className={`flex-1 rounded-sm ${TONE_BG[toneForPercent(point, GAUGE_WARN, GAUGE_BAD)]} opacity-60`}
                style={{ height: Math.max(2, Math.min(100, point)) + "%" }}
              />
            ))}
          </div>
        )}
        {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

interface HostState {
  cpu: { percent: number | null; cores: number; model: string | null; load: { "1m": number | null; "5m": number | null; "15m": number | null }; per_core: number[] };
  memory: { total_bytes: number | null; used_bytes: number | null; available_bytes: number | null; percent: number | null; swap_total_bytes: number | null; swap_used_bytes: number | null };
  disk: { mounts: Array<{ path: string; total_bytes: number; used_bytes: number; free_bytes: number; percent: number }>; io: Array<{ device: string; read?: number; write?: number }> };
  network: { interfaces: Array<{ name: string; rx?: number; tx?: number; rx_bytes?: number; tx_bytes?: number }> };
  uptime: { uptime_seconds: number | null };
  top_processes: Array<{ pid: number; name: string; rss_bytes: number }>;
}

interface AiState {
  state: "ok" | "unsupported" | "error";
  reason?: string | null;
  api_key_masked?: string | null;
  base_url?: string | null;
  configured_models?: { chat?: string; embedding?: string; rerank?: string };
  credit: { remaining_irt: number | null; remaining_unit: number | null; account_tier: number | null; exchange_rate: number | null } | null;
  usage: { period_start?: string; period_end?: string; transactions?: number; tokens_total?: number; tokens_cached?: number; cost_unit?: number | null; cost_irt?: number | null } | null;
  usage_by_model: Array<{ model: string; transactions: number; tokens: number; cost_unit: number | null }>;
  packages: Array<{ name: string; remaining_irt: number | null; days_left: number | null; models: string[] }>;
  covered_models: string[];
}

interface ModelCheck {
  ok: boolean;
  state: string;
  model: string | null;
  latency_ms?: number;
  code?: string;
  detail?: string;
}

/** Poll every 15s: often enough that a problem appears while the PO watches,
 * slow enough that it never approaches the provider's account-API tier limit. */
const POLL_MS = 15000;
const HISTORY = 24;

function useGaugeHistory(value: number | null): number[] {
  const [history, setHistory] = useState<number[]>([]);
  const last = useRef<number | null>(null);
  useEffect(() => {
    if (value === null || value === last.current) return;
    last.current = value;
    setHistory((prev) => [...prev, value].slice(-HISTORY));
  }, [value]);
  return history;
}

interface BackupState {
  state: "ok" | "stale" | "missing" | "unavailable";
  detail?: string;
  files: number;
  latest: { name: string; size_bytes: number; age_hours: number; created_at: string } | null;
}

// A backup the PO believes in but that does not exist is worse than none at
// all - the gap is discovered during a restore. So the state is spelled out,
// including the age, rather than shown as a green tick.
const BACKUP_FA: Record<BackupState["state"], string> = {
  ok: "پشتیبان‌گیری منظم انجام می‌شود.",
  stale: "آخرین نسخهٔ پشتیبان قدیمی است؛ زمان‌بندی پشتیبان‌گیری را بررسی کنید.",
  missing: "هیچ فایل پشتیبانی پیدا نشد.",
  unavailable: "پوشهٔ پشتیبان روی سرور در دسترس برنامه نیست.",
};

export function MonitoringTab({ token }: { token: string }) {
  const [host, setHost] = useState<HostState | null>(null);
  const [ai, setAi] = useState<AiState | null>(null);
  const [check, setCheck] = useState<ModelCheck | null>(null);
  const [backup, setBackup] = useState<BackupState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [hostData, aiData, backupData] = await Promise.all([
        adminApi<HostState>(token, "GET", "/monitoring/host"),
        adminApi<AiState>(token, "GET", "/monitoring/ai"),
        adminApi<BackupState>(token, "GET", "/system-status/backup"),
      ]);
      setHost(hostData);
      setAi(aiData);
      setBackup(backupData);
      setError(null);
      setUpdatedAt(new Date());
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setError(err instanceof Error ? err.message : "دریافت وضعیت سرور ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const runCheck = useCallback(async () => {
    setChecking(true);
    try {
      setCheck(await adminApi<ModelCheck>(token, "GET", "/monitoring/model-check"));
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setCheck(null);
      setError(err instanceof Error ? err.message : "آزمایش مدل ناموفق بود.");
    } finally {
      setChecking(false);
    }
  }, [token]);

  const cpuHistory = useGaugeHistory(host?.cpu.percent ?? null);
  const memHistory = useGaugeHistory(host?.memory.percent ?? null);
  const diskPercent = host?.disk.mounts[0]?.percent ?? null;
  const diskHistory = useGaugeHistory(diskPercent);

  if (error && !host) {
    return <Retry message={error} onRetry={() => void load()} />;
  }

  const credit = ai?.credit;
  const packageDays = ai?.packages?.[0]?.days_left ?? null;
  // Running out of both balance and package time is the one failure mode that
  // stops every answer, so it is promoted to a banner rather than a card row.
  const creditLow = Boolean(credit && credit.remaining_irt !== null && credit.remaining_irt < 100000);
  const packageExpiring = packageDays !== null && packageDays <= 3;

  return (
    <div className="space-y-6" data-testid="monitoring-tab">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-black">پایش سرور و حساب هوش مصنوعی</h2>
          <p className="text-xs text-muted-foreground">
            {updatedAt ? "آخرین به‌روزرسانی: " + updatedAt.toLocaleTimeString("fa-IR") : "در حال دریافت…"}
            {" · "}
            هر {faNum(POLL_MS / 1000)} ثانیه به‌روز می‌شود
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-2 rounded-control border px-3 py-1.5 text-xs font-bold hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          به‌روزرسانی
        </button>
      </div>

      {(creditLow || packageExpiring) && (
        <div className="flex items-start gap-3 rounded-control border border-warning bg-warning-bg px-4 py-3" data-testid="ai-credit-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="space-y-1 text-[13px]">
            <p className="font-bold text-warning">اعتبار سرویس هوش مصنوعی در حال اتمام است.</p>
            {packageExpiring && (
              <p className="text-muted-foreground">
                بستهٔ فعلی {faNum(packageDays, 1)} روز دیگر منقضی می‌شود. پیش از آن اعتبار تازه تهیه کنید تا پاسخ‌دهی متوقف نشود.
              </p>
            )}
            {creditLow && (
              <p className="text-muted-foreground">
                موجودی باقی‌مانده {faNum(credit?.remaining_irt)} تومان است.
              </p>
            )}
          </div>
        </div>
      )}

      {/* --- host ---------------------------------------------------------- */}
      <section className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-black">
          <Server className="size-4" /> منابع سرور
        </h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Gauge2
            title="پردازنده"
            icon={<Cpu className="size-4" />}
            percent={host?.cpu.percent ?? null}
            detail={
              host
                ? faNum(host.cpu.cores) + " هسته · بار " + faNum(host.cpu.load["1m"], 2)
                : "—"
            }
            hint={host?.cpu.model ?? undefined}
            history={cpuHistory}
          />
          <Gauge2
            title="حافظه"
            icon={<MemoryStick className="size-4" />}
            percent={host?.memory.percent ?? null}
            detail={
              host?.memory.total_bytes
                ? bytes(host.memory.used_bytes) + " از " + bytes(host.memory.total_bytes)
                : "—"
            }
            hint={
              host?.memory.swap_total_bytes
                ? "سواپ: " + bytes(host.memory.swap_used_bytes) + " از " + bytes(host.memory.swap_total_bytes)
                : undefined
            }
            history={memHistory}
          />
          <Gauge2
            title="فضای دیسک"
            icon={<HardDrive className="size-4" />}
            percent={diskPercent}
            detail={
              host?.disk.mounts[0]
                ? bytes(host.disk.mounts[0].free_bytes) + " آزاد از " + bytes(host.disk.mounts[0].total_bytes)
                : "—"
            }
            hint={host ? "مدت روشن بودن: " + duration(host.uptime.uptime_seconds) : undefined}
            history={diskHistory}
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <Network className="size-4" /> شبکه
              </CardTitle>
            </CardHeader>
            <CardContent>
              {host?.network.interfaces.length ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>رابط</TableHead>
                      <TableHead>دریافت</TableHead>
                      <TableHead>ارسال</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {host.network.interfaces.map((iface) => (
                      <TableRow key={iface.name}>
                        <TableCell className="font-mono text-xs">{iface.name}</TableCell>
                        <TableCell>{rate(iface.rx)}</TableCell>
                        <TableCell>{rate(iface.tx)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-xs text-muted-foreground">
                  داده‌ای در دسترس نیست. دو نمونهٔ پیاپی برای محاسبهٔ سرعت لازم است.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <Gauge className="size-4" /> پرکاربردترین پردازش‌ها
              </CardTitle>
              <CardDescription className="text-xs">بر پایهٔ حافظهٔ مصرفی</CardDescription>
            </CardHeader>
            <CardContent>
              {host?.top_processes.length ? (
                <ul className="space-y-2">
                  {host.top_processes.map((proc) => (
                    <li key={proc.pid} className="flex items-center justify-between gap-3 text-xs">
                      <span className="truncate font-mono" title={proc.name}>
                        {proc.name}
                      </span>
                      <span className="shrink-0 font-bold">{bytes(proc.rss_bytes)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">داده‌ای در دسترس نیست.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      {/* --- ai account ---------------------------------------------------- */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-sm font-black">
            <Sparkles className="size-4" /> حساب هوش مصنوعی
          </h3>
          <button
            type="button"
            onClick={() => void runCheck()}
            disabled={checking}
            className="flex items-center gap-2 rounded-control border px-3 py-1.5 text-xs font-bold hover:bg-muted disabled:opacity-50"
            data-testid="model-check-button"
          >
            {checking ? <RefreshCw className="size-3.5 animate-spin" /> : <Activity className="size-3.5" />}
            آزمایش مدل پاسخ‌دهی
          </button>
        </div>

        {check && (
          <div
            className={`flex items-start gap-3 rounded-control border px-4 py-3 ${check.ok ? "border-success bg-success-bg" : "border-error bg-error-bg"}`}
            data-testid="model-check-result"
          >
            {check.ok ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
            ) : (
              <XCircle className="mt-0.5 size-4 shrink-0 text-error" />
            )}
            <div className="space-y-1 text-[13px]">
              <p className={check.ok ? "font-bold text-success" : "font-bold text-error"}>
                {check.ok ? "مدل پاسخ داد و آمادهٔ استفاده است." : "مدل پاسخ نداد."}
              </p>
              <p className="text-muted-foreground">
                مدل: <span className="font-mono">{check.model ?? "—"}</span>
                {check.ok && check.latency_ms !== undefined && " · زمان پاسخ: " + faNum(check.latency_ms) + " میلی‌ثانیه"}
                {!check.ok && check.detail && " · " + persianError(check.code ?? "UNKNOWN", undefined, check.detail)}
              </p>
            </div>
          </div>
        )}

        {ai?.state === "unsupported" && (
          <Surface className="p-4">
            <p className="text-xs text-muted-foreground">
              سرویس هوش مصنوعی فعلی امکان گزارش اعتبار را ارائه نمی‌دهد. بردارسازی و رتبه‌بندی روی همین سرور انجام می‌شود و اعتباری مصرف نمی‌کند.
            </p>
          </Surface>
        )}

        {ai?.state === "error" && (
          <Surface className="p-4">
            <p className="text-xs text-error">
              دریافت اطلاعات حساب ناموفق بود. نشانی سرویس و کلید را در بخش تنظیمات بررسی کنید.
            </p>
          </Surface>
        )}

        {ai?.state === "ok" && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-xs font-bold text-muted-foreground">
                    <Database className="size-3.5" /> موجودی کل
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-black" data-testid="ai-balance">
                    {faNum(credit?.remaining_irt)} <span className="text-xs font-normal">تومان</span>
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-bold text-muted-foreground">مصرف ۲۴ ساعت گذشته</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-black">{faNum(ai.usage?.cost_unit, 2)} <span className="text-xs font-normal">واحد</span></p>
                  <p className="text-[11px] text-muted-foreground">{faNum(ai.usage?.transactions)} درخواست</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-bold text-muted-foreground">توکن مصرفی</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-black">{faNum(ai.usage?.tokens_total)}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {ai.usage?.tokens_cached ? faNum(ai.usage.tokens_cached) + " از حافظهٔ نهان" : "—"}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-bold text-muted-foreground">سطح حساب</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-black">{faNum(credit?.account_tier)}</p>
                  <p className="text-[11px] text-muted-foreground">کلید: {ai.api_key_masked ?? "—"}</p>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-bold">مصرف به تفکیک مدل</CardTitle>
                  <CardDescription className="text-xs">۲۴ ساعت گذشته</CardDescription>
                </CardHeader>
                <CardContent>
                  {ai.usage_by_model.length ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>مدل</TableHead>
                          <TableHead>درخواست</TableHead>
                          <TableHead>توکن</TableHead>
                          <TableHead>هزینه (واحد)</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {ai.usage_by_model.slice(0, 8).map((row) => (
                          <TableRow key={row.model}>
                            <TableCell className="font-mono text-xs">{row.model}</TableCell>
                            <TableCell>{faNum(row.transactions)}</TableCell>
                            <TableCell>{faNum(row.tokens)}</TableCell>
                            <TableCell className="font-bold">{faNum(row.cost_unit, 3)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <p className="text-xs text-muted-foreground">در این بازه مصرفی ثبت نشده است.</p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-bold">بسته‌های اعتبار</CardTitle>
                  <CardDescription className="text-xs">
                    اعتبار هر بسته فقط برای مدل‌های فهرست‌شده در آن قابل استفاده است
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {ai.packages.length ? (
                    ai.packages.map((pkg) => (
                      <div key={pkg.name} className="space-y-1.5 rounded-control border p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-bold">{pkg.name}</span>
                          <span
                            className={`text-xs font-bold ${pkg.days_left !== null && pkg.days_left <= 3 ? "text-error" : "text-muted-foreground"}`}
                          >
                            {pkg.days_left !== null ? faNum(pkg.days_left, 1) + " روز مانده" : "—"}
                          </span>
                        </div>
                        <p className="text-sm font-black">{faNum(pkg.remaining_irt)} <span className="text-xs font-normal">تومان</span></p>
                        <p className="text-[11px] leading-5 text-muted-foreground">
                          {faNum(pkg.models.length)} مدل مجاز
                          {ai.configured_models?.chat && (
                            <>
                              {" · "}
                              مدل پاسخ‌دهی{" "}
                              <span className={pkg.models.includes(ai.configured_models.chat) ? "font-bold text-success" : "font-bold text-error"}>
                                {pkg.models.includes(ai.configured_models.chat) ? "در این بسته هست" : "در این بسته نیست"}
                              </span>
                            </>
                          )}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-muted-foreground">بستهٔ اعتباری فعالی وجود ندارد.</p>
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        )}

        {backup && (
          <Card data-testid="backup-card">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <HardDrive className="size-4" /> پشتیبان‌گیری پایگاه داده
              </CardTitle>
              <CardDescription className="text-xs">
                پشتیبان شبانه با pg_dump روی همین سرور گرفته می‌شود.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <div
                className="flex items-start gap-2 text-[13px]"
                data-testid="backup-state"
              >
                {backup.state === "ok" ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                ) : (
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                )}
                <span className={backup.state === "ok" ? "text-success" : "font-bold text-warning"}>
                  {BACKUP_FA[backup.state]}
                </span>
              </div>
              {backup.latest && (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
                  <div>
                    <dt className="text-[11px] text-muted-foreground">آخرین نسخه</dt>
                    <dd className="font-bold">{new Date(backup.latest.created_at).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" })}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-muted-foreground">قدمت</dt>
                    <dd className="font-bold">{faNum(backup.latest.age_hours, 1)} ساعت</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-muted-foreground">حجم</dt>
                    <dd className="font-bold">{bytes(backup.latest.size_bytes)}</dd>
                  </div>
                  <div className="col-span-2 sm:col-span-3">
                    <dt className="text-[11px] text-muted-foreground">نام فایل</dt>
                    <dd className="truncate font-mono text-[11px]" dir="ltr">
                      {backup.latest.name}
                    </dd>
                  </div>
                </dl>
              )}
              <p className="text-[11px] text-muted-foreground">
                {faNum(backup.files)} نسخه روی سرور نگه داشته می‌شود.
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}