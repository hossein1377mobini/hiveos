import { useEffect, useRef, useState } from "react"
import { AlertTriangleIcon, DatabaseIcon, HardDriveIcon, RefreshCwIcon, ServerIcon } from "lucide-react"

import { Button } from "../../components/ui/button"
import { DomainStatus } from "../../components/ui/domain-status"
import { Surface } from "../../components/ui/surface"
import { cn } from "../../lib/utils"
import { faNum, faRelative, humanSize } from "../../lib/dates"
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
  if (!host.data) return <p className="text-caption text-muted-foreground">در حال دریافت وضعیت سرور…</p>

  const data = host.data

  return (
    <div className="grid gap-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-micro text-muted-foreground">
          خودکار هر ۳۰ ثانیه · مدت کارکرد سرور {faRelative(uptimeToIso(data.uptime.uptime_seconds))}
        </p>
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
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <GaugeCard label="پردازنده" percent={data.cpu.percent} hint={data.cpu.model + " · " + faNum(data.cpu.cores) + " هسته"} />
        <GaugeCard
          label="حافظه"
          percent={data.memory.percent}
          hint={humanSize(data.memory.used_bytes) + " از " + humanSize(data.memory.total_bytes)}
        />
        {data.disk.mounts.slice(0, 2).map((mount) => (
          <GaugeCard
            key={mount.path}
            label={"فضای دیسک — " + mount.path}
            percent={mount.percent}
            hint={humanSize(mount.free_bytes) + " آزاد از " + humanSize(mount.total_bytes)}
          />
        ))}
      </div>

      <BackupCard state={backup.data} error={backup.error} onRetry={() => void backup.reload()} />

      <div className="grid gap-3 lg:grid-cols-2">
        <Surface>
          <h2 className="flex items-center gap-2 text-subheading">
            <ServerIcon aria-hidden className="size-4 text-muted-foreground" />
            میانگین بار
          </h2>
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
          <h2 className="flex items-center gap-2 text-subheading">
            <HardDriveIcon aria-hidden className="size-4 text-muted-foreground" />
            پرترافیک‌ترین پردازش‌ها
          </h2>
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
          <h2 className="flex items-center gap-2 text-subheading">
            <DatabaseIcon aria-hidden className="size-4 text-muted-foreground" />
            پشتیبان‌گیری شبانه
          </h2>
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
