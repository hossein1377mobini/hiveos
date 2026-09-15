import { useEffect, useRef, useState } from "react"
import {
  AlertTriangleIcon,
  CpuIcon,
  DatabaseIcon,
  HardDriveIcon,
  NetworkIcon,
  RefreshCwIcon,
  ServerIcon,
} from "lucide-react"

import { BarChart } from "../../components/ui/chart"
import { Button } from "../../components/ui/button"
import { DomainStatus } from "../../components/ui/domain-status"
import { Surface } from "../../components/ui/surface"
import { cn } from "../../lib/utils"
import { faNum, faRelative, humanSize } from "../../lib/dates"
import { LoadingPanel, PageHeader, SectionHeading } from "../page-layout"
import { useLive, Retry } from "../useLive"

interface HostSnapshot {
  cpu: { percent: number; cores: number; model: string; load: Record<string, number>; per_core: number[] }
  memory: {
    total_bytes: number
    used_bytes: number
    available_bytes: number
    percent: number
    swap_total_bytes: number
    swap_used_bytes: number
  }
  disk: {
    mounts: Array<{ path: string; total_bytes: number; used_bytes: number; free_bytes: number; percent: number }>
    io: Array<Record<string, unknown>>
  }
  network: { interfaces: Array<{ name: string; rx: number; tx: number }> }
  uptime: { uptime_seconds: number }
  top_processes: Array<{ pid: number; name: string; rss_bytes: number }>
}

interface BackupSnapshot {
  state: string
  files: number
  latest: { name: string; size_bytes: number; age_hours: number; created_at: string } | null
  reason?: string
}

/**
 * Operations workspace.
 *
 * v0.1 rendered CPU, memory and disk as hand-positioned divs with an inline
 * height percentage and key={index} — a chart with no accessible name, no value
 * for a screen reader and a React key that changes on every poll. Gauges carry
 * role="progressbar" and real values now, and the nightly backup's freshness is
 * called out as its own card because a cron that silently stopped is exactly
 * what this page exists to catch. [E2/F3]
 */
export default function OperationsView({ token }: { token: string }) {
  const host = useLive<HostSnapshot>(token, "/monitoring/host", 30_000)
  const backup = useLive<BackupSnapshot>(token, "/system-status/backup", 60_000)

  if (host.error && !host.data) {
    return <Retry message={host.error} onRetry={() => void host.reload()} />
  }
  if (!host.data) return <LoadingPanel label="در حال دریافت وضعیت سرور…" />

  const data = host.data

  return (
    <div className="grid gap-5">
      {/* Same header shape as every other workspace: a title, the sentence that
          explains what is on screen, and the row's action on the far side. v0.1
          put a bare timestamp line here, so this page had no heading at all
          where the other admin pages had one. */}
      <PageHeader
        title="وضعیت سرور"
        description={
          "خودکار هر ۳۰ ثانیه · مدت کارکرد سرور " +
          faRelative(uptimeToIso(data.uptime.uptime_seconds))
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            className="rounded-control"
            onClick={() => {
              void host.reload()
              void backup.reload()
            }}
          >
            <RefreshCwIcon className="size-3.5" />
            به‌روزرسانی
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <GaugeCard label="پردازنده" percent={data.cpu.percent} hint={data.cpu.model + " · " + faNum(data.cpu.cores) + " هسته"} />
        <GaugeCard
          label="حافظه"
          percent={data.memory.percent}
          hint={humanSize(data.memory.used_bytes) + " از " + humanSize(data.memory.total_bytes)}
        />
        {/* Every mount, not the first two: a full /var or /tmp is exactly the
            kind of disk problem this page exists to surface, and it is rarely
            the first entry in the list. The grid wraps, so a long list reads as
            another row of gauges rather than a cramped strip. */}
        {data.disk.mounts.map((mount) => (
          <GaugeCard
            key={mount.path}
            label={"فضای دیسک — " + mount.path}
            percent={mount.percent}
            hint={humanSize(mount.free_bytes) + " آزاد از " + humanSize(mount.total_bytes)}
          />
        ))}
      </div>

      <BackupCard state={backup.data} error={backup.error} onRetry={() => void backup.reload()} />

      {/* The endpoint has always returned per-core load, swap, disk I/O and the
          network interfaces; none of it was rendered, so a saturated single core
          or a machine swapping hard looked identical to a healthy one. Each of
          these is shown only when the server reports it - an empty section is
          worse than an absent one. */}
      {data.memory.swap_total_bytes > 0 && (
        <Surface>
          <SectionHeading className="flex items-center gap-2">
            <HardDriveIcon aria-hidden className="size-4 text-muted-foreground" />
            حافظهٔ مبادله (Swap)
          </SectionHeading>
          <div className="mt-3">
            <BarChart
              valueLabel=""
              data={[
                { label: "استفاده‌شده", value: Math.round(data.memory.swap_used_bytes / 1024 / 1024) },
                {
                  label: "آزاد",
                  value: Math.round(
                    Math.max(0, data.memory.swap_total_bytes - data.memory.swap_used_bytes) / 1024 / 1024,
                  ),
                },
              ]}
            />
          </div>
          <p className="mt-2 text-micro text-muted-foreground">
            مقدار بر حسب مگابایت. مصرف مداوم swap یعنی حافظهٔ اصلی کافی نیست.
          </p>
        </Surface>
      )}

      {data.network.interfaces.length > 0 && (
        <Surface>
          <SectionHeading className="flex items-center gap-2">
            <NetworkIcon aria-hidden className="size-4 text-muted-foreground" />
            شبکه
          </SectionHeading>
          <p className="mt-1 text-micro text-muted-foreground">
            مجموع ترافیک دریافت و ارسال از زمان روشن شدن سرور.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-caption">
              <thead>
                <tr className="border-b border-border text-micro text-muted-foreground">
                  <th className="py-2 text-start font-bold">رابط</th>
                  <th className="py-2 text-end font-bold">دریافت</th>
                  <th className="py-2 text-end font-bold">ارسال</th>
                </tr>
              </thead>
              <tbody>
                {data.network.interfaces.map((entry) => (
                  <tr key={entry.name} className="border-b border-border last:border-0">
                    <td className="mono py-2" dir="ltr">
                      {entry.name}
                    </td>
                    <td data-numeric className="py-2 text-end text-muted-foreground">
                      {humanSize(entry.rx)}
                    </td>
                    <td data-numeric className="py-2 text-end text-muted-foreground">
                      {humanSize(entry.tx)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>
      )}

      {data.cpu.per_core.length > 1 && (
        <Surface>
          <SectionHeading className="flex items-center gap-2">
            <CpuIcon aria-hidden className="size-4 text-muted-foreground" />
            بار هر هسته
          </SectionHeading>
          <p className="mt-1 text-micro text-muted-foreground">
            میانگین کل می‌تواند پنهان کند که یک هسته اشباع شده است.
          </p>
          <div className="mt-3 flex h-24 items-end gap-1">
            {data.cpu.per_core.map((core, index) => (
              <div key={index} className="flex h-full flex-1 flex-col justify-end gap-1">
                <div
                  role="progressbar"
                  aria-label={"هستهٔ " + faNum(index + 1)}
                  aria-valuenow={Math.round(core)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="w-full overflow-hidden rounded-xs bg-secondary"
                  style={{ height: Math.max(3, Math.min(100, core)) + "%" }}
                >
                  <div className={cn("h-full w-full rounded-xs", toneFor(core))} />
                </div>
                <span data-numeric className="text-center text-micro text-muted-foreground">
                  {faNum(Math.round(core))}
                </span>
              </div>
            ))}
          </div>
        </Surface>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <Surface>
          <SectionHeading className="flex items-center gap-2">
            <ServerIcon aria-hidden className="size-4 text-muted-foreground" />
            میانگین بار
          </SectionHeading>
          <dl className="mt-3 grid grid-cols-3 gap-3 text-caption">
            {(["1m", "5m", "15m"] as const).map((window) => (
              <div key={window}>
                <dt className="text-micro text-muted-foreground">{window === "1m" ? "۱ دقیقه" : window === "5m" ? "۵ دقیقه" : "۱۵ دقیقه"}</dt>
                <dd data-numeric className="font-bold">
                  {data.cpu.load?.[window] ?? "—"}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-micro text-muted-foreground">
            عدد بزرگ‌تر از تعداد هسته‌ها یعنی پردازنده از توان خود بیشتر بار گرفته است.
          </p>
        </Surface>

        <Surface>
          <SectionHeading className="flex items-center gap-2">
            <HardDriveIcon aria-hidden className="size-4 text-muted-foreground" />
            پرترافیک‌ترین پردازش‌ها
          </SectionHeading>
          {data.top_processes.length === 0 ? (
            <p className="mt-3 text-caption text-muted-foreground">داده‌ای گزارش نشده است.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {data.top_processes.slice(0, 5).map((process) => (
                <li key={process.pid} className="flex items-center gap-3 py-2 text-caption">
                  <span className="mono min-w-0 flex-1 truncate" dir="ltr">
                    {process.name}
                  </span>
                  <span data-numeric className="text-muted-foreground">
                    {humanSize(process.rss_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Surface>
      </div>
    </div>
  )
}

/** Thresholds are deliberately conservative: the operator should learn about a
 * filling disk long before it becomes an outage. */
const GAUGE_WARN = 75
const GAUGE_BAD = 90

function toneFor(percent: number): string {
  if (percent >= GAUGE_BAD) return "bg-error"
  if (percent >= GAUGE_WARN) return "bg-warning"
  return "bg-success"
}

/**
 * Keeps the last few readings of a live value.
 *
 * A single number says what the value is right now, not where it is going — a
 * disk at 60% that was at 20% an hour ago is a different problem from one that
 * has sat at 60% for a week. The sparkline is decorative for a screen reader
 * (the progressbar above it carries the value), so it stays aria-hidden.
 */
function useGaugeHistory(value: number | null): number[] {
  const [history, setHistory] = useState<number[]>([])
  const last = useRef<number | null>(null)
  useEffect(() => {
    if (value === null || value === last.current) return
    last.current = value
    setHistory((previous) => [...previous, value].slice(-HISTORY))
  }, [value])
  return history
}

function GaugeCard({ label, percent, hint }: { label: string; percent: number; hint: string }) {
  const value = Math.round(percent * 10) / 10
  const history = useGaugeHistory(value)
  return (
    <Surface className="grid gap-2">
      <span className="text-micro font-bold text-muted-foreground">{label}</span>
      <span data-numeric data-testid={"gauge-value-" + label} className="text-display leading-none">
        {faNum(value, 1)}٪
      </span>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(value)}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
      >
        <div className={cn("h-full rounded-full", toneFor(value))} style={{ width: Math.min(100, value) + "%" }} />
      </div>
      {history.length > 1 && (
        <div aria-hidden className="flex h-5 items-end gap-0.5">
          {/* The reading itself is the key: two samples of the same value are the
              same bar, and using the array index reset every bar's identity on
              each poll. [E2] */}
          {history.map((point, index) => (
            <div
              key={index + ":" + point}
              className={cn("flex-1 rounded-xs opacity-60", toneFor(point))}
              style={{ height: Math.max(2, Math.min(100, point)) + "%" }}
            />
          ))}
        </div>
      )}
      <span className="text-micro text-muted-foreground">{hint}</span>
    </Surface>
  )
}

/**
 * Readings kept for the sparkline. 24 samples at a 30s poll is ~12 minutes.
 */
const HISTORY = 24

/**
 * The nightly backup is the one operational fact the PO cannot verify any other
 * way, so its age is stated in days instead of a timestamp they would have to
 * subtract in their head.
 */
function BackupCard({
  state,
  error,
  onRetry,
}: {
  state: BackupSnapshot | null
  error: string | null
  onRetry: () => void
}) {
  if (error && !state) return <Retry message={error} onRetry={onRetry} />
  if (!state) {
    return (
      <Surface>
        <p className="text-caption text-muted-foreground">در حال بررسی پشتیبان‌گیری…</p>
      </Surface>
    )
  }

  const stale = state.state === "stale"
  return (
    <Surface data-testid="backup-card" className={cn(stale && "border-warning-border bg-warning-bg")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <SectionHeading className="flex items-center gap-2">
            <DatabaseIcon aria-hidden className="size-4 text-muted-foreground" />
            پشتیبان‌گیری شبانه
          </SectionHeading>
          <span data-testid="backup-state">
            <DomainStatus domain="health" value={state.state} />
          </span>
          {stale && (
            <p className="flex items-center gap-1.5 text-caption text-warning">
              <AlertTriangleIcon aria-hidden className="size-3.5" />
              آخرین پشتیبان قدیمی است؛ زمان‌بندی سرور را بررسی کنید.
            </p>
          )}
        </div>
        <div className="grid gap-1 text-end text-caption">
          <span data-numeric className="font-bold">
            {state.latest
              ? faNum(Math.round(state.latest.age_hours / 24 * 10) / 10, 1) + " روز پیش"
              : "پشتیبانی ثبت نشده"}
          </span>
          <span className="text-micro text-muted-foreground">
            {faNum(state.files)} فایل پشتیبان
          </span>
          {state.latest && (
            <span className="mono text-micro text-muted-foreground" dir="ltr">
              {state.latest.name} · {humanSize(state.latest.size_bytes)}
            </span>
          )}
        </div>
      </div>
    </Surface>
  )
}

function uptimeToIso(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString()
}
