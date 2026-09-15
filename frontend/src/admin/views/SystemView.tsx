import { Button } from "../../components/ui/button"
import { DomainStatus } from "../../components/ui/domain-status"
import { ErrorText } from "../../components/ui/error-text"
import { Surface } from "../../components/ui/surface"
import { faNum, faDateTime, faRelative, humanSize } from "../../lib/dates"
import { LoadingPanel, SectionHeading } from "../page-layout"
import { useLive, Retry } from "../useLive"

interface LiveStatus {
  health: string
  generated_at?: string
  uptime_seconds: number
  environment?: string
  db: {
    state: string
    migration_head: string | null
    expected_head?: string | null
    migrations_ok?: boolean
    latency_ms: number
    size_bytes?: number | null
    connections?: number | null
  }
  counters: Record<string, number>
  last_audit_at?: string | null
  jobs: { open: number; by_status: Record<string, number> }
  process: { pid: number; started_at?: string; threads?: number | null }
  host: {
    load: { "1m": number | null; "5m": number | null; "15m": number | null }
    disk: {
      root: string | null
      total_bytes: number | null
      free_bytes: number | null
      uploads_bytes: number | null
    }
  }
  llm_provider: string
  sms_provider: string
  embedding_provider: string
  services: Record<string, string>
}

/**
 * System status workspace.
 *
 * v0.1 reported a list of values with no structure: load averages, provider
 * names and counters all read the same weight, and a degraded service looked
 * exactly like a healthy one. Health is a badge now and every panel states what
 * it is measuring. [D4/D14]
 */
export default function SystemView({ token }: { token: string }) {
  const { data, error, updatedAt, reload } = useLive<LiveStatus>(token, "/system-status", 15_000)

  if (error && !data) return <Retry message={error} onRetry={() => void reload()} />
  if (!data) return <LoadingPanel label="در حال دریافت وضعیت سامانه…" />

  const jobRows = Object.entries(data.jobs.by_status ?? {})

  return (
    <div className="grid gap-4">
      <Surface className="flex flex-wrap items-center justify-between gap-3">
        <div className="grid gap-1">
          <span className="flex items-center gap-2">
            <span className="text-micro font-bold text-muted-foreground">وضعیت کلی</span>
            <span data-testid="overall">
              <DomainStatus domain="health" value={data.health} />
            </span>
          </span>
          <span className="text-micro text-muted-foreground">
            آخرین به‌روزرسانی {faDateTime(updatedAt ?? undefined)} · خودکار هر ۱۵ ثانیه
          </span>
        </div>
        <Button variant="outline" size="sm" className="rounded-control" onClick={() => void reload()}>
          به‌روزرسانی
        </Button>
      </Surface>

      <ErrorText>{error}</ErrorText>

      <div className="grid gap-3 lg:grid-cols-3">
        <Surface>
          <SectionHeading className="mb-3">سرور برنامه</SectionHeading>
          <dl className="grid gap-2 text-caption">
            <Row label="محیط اجرا" value={<span dir="ltr">{data.environment ?? "—"}</span>} />
            <Row label="مدت کارکرد" value={faRelative(uptimeToIso(data.uptime_seconds))} />
            <Row label="شناسهٔ فرایند" value={<span data-numeric dir="ltr">{data.process?.pid ?? "—"}</span>} />
            <Row label="نخ‌های فعال" value={<span data-numeric>{faNum(data.process?.threads ?? 0)}</span>} />
            <Row
              label="میانگین بار (۱ / ۵ / ۱۵ دقیقه)"
              value={
                <span data-numeric dir="ltr">
                  {[data.host?.load?.["1m"], data.host?.load?.["5m"], data.host?.load?.["15m"]]
                    .map((value) => (value === null || value === undefined ? "—" : value))
                    .join(" / ")}
                </span>
              }
            />
          </dl>
        </Surface>

        <Surface>
          <SectionHeading className="mb-3">پایگاه داده</SectionHeading>
          <dl className="grid gap-2 text-caption">
            <Row
              label="وضعیت"
              value={
                <span className={data.db.state === "up" ? "text-success" : "text-error"}>
                  {data.db.state === "up" ? "در دسترس" : "قطع"}
                </span>
              }
            />
            <Row label="تأخیر پاسخ" value={<span data-numeric>{faNum(data.db.latency_ms)} میلی‌ثانیه</span>} />
            <Row label="اتصال‌های فعال" value={<span data-numeric>{faNum(data.db.connections ?? 0)}</span>} />
            <Row label="حجم پایگاه داده" value={<span data-numeric>{humanSize(Number(data.db.size_bytes ?? 0))}</span>} />
            <Row
              label="نسخهٔ مایگریشن"
              value={
                <>
                  <span className="mono" dir="ltr">
                    {data.db.migration_head ?? "—"}
                  </span>
                  {data.db.migrations_ok === false && (
                    <span className="ms-2 text-error">با فایل‌های مایگریشن هم‌خوان نیست</span>
                  )}
                </>
              }
            />
          </dl>
        </Surface>

        <Surface>
          <SectionHeading className="mb-3">فضای ذخیره‌سازی</SectionHeading>
          <dl className="grid gap-2 text-caption">
            <Row label="مسیر" value={<span className="mono" dir="ltr">{data.host?.disk?.root ?? "—"}</span>} />
            <Row label="فضای کل" value={<span data-numeric>{humanSize(Number(data.host?.disk?.total_bytes ?? 0))}</span>} />
            <Row
              label="فضای آزاد"
              value={
                <span
                  data-numeric
                  className={
                    diskTight(data.host?.disk?.total_bytes, data.host?.disk?.free_bytes)
                      ? "font-bold text-warning"
                      : undefined
                  }
                >
                  {humanSize(Number(data.host?.disk?.free_bytes ?? 0))}
                </span>
              }
            />
            <Row
              label="حجم فایل‌های بارگذاری‌شده"
              value={<span data-numeric>{humanSize(Number(data.host?.disk?.uploads_bytes ?? 0))}</span>}
            />
          </dl>
        </Surface>
      </div>

      <Surface>
        <SectionHeading className="mb-3">صف پردازش</SectionHeading>
        <p className="text-caption">
          کارهای در جریان:{" "}
          <span data-numeric data-testid="jobs-open" className="font-bold">
            {faNum(data.jobs.open)}
          </span>
        </p>
        {jobRows.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {jobRows.map(([status, count]) => (
              <span key={status} className="flex items-center gap-1.5">
                <DomainStatus domain="job" value={status} />
                <span data-numeric className="text-micro text-muted-foreground">
                  {faNum(count)}
                </span>
              </span>
            ))}
          </div>
        )}
      </Surface>

      <Surface>
        <SectionHeading className="mb-3">سرویس‌های وابسته</SectionHeading>
        <dl className="grid gap-2 text-caption sm:grid-cols-3">
          <Row label="مدل زبانی" value={<span className="mono" dir="ltr">{data.llm_provider}</span>} />
          <Row label="پیامک" value={<span className="mono" dir="ltr">{data.sms_provider}</span>} />
          <Row label="جست‌وجوی معنایی" value={<span className="mono" dir="ltr">{data.embedding_provider}</span>} />
          {Object.entries(data.services ?? {}).map(([name, state]) => (
            <Row
              key={name}
              label={<span className="mono" dir="ltr">{name}</span>}
              value={
                <span className={state === "up" ? "text-success" : "text-error"}>
                  {state === "up" ? "در دسترس" : state}
                </span>
              }
            />
          ))}
        </dl>
        <p className="mt-3 text-micro text-muted-foreground">
          آخرین رویداد ثبت‌شده: {faDateTime(data.last_audit_at ?? undefined)}
        </p>
      </Surface>
    </div>
  )
}

function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate font-bold text-foreground">{value}</dd>
    </div>
  )
}

/** The server's uptime is a duration; express its start as a relative instant. */
function uptimeToIso(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString()
}

/** Warn while there is still room to act — 10% free or less. */
function diskTight(total: number | null | undefined, free: number | null | undefined): boolean {
  if (!total || free === null || free === undefined) return false
  return free / total <= 0.1
}