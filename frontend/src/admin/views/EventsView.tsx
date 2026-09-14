import { useCallback, useEffect, useState } from "react"
import { ScrollTextIcon } from "lucide-react"

import { Button } from "../../components/ui/button"
import { DataTable, type DataTableColumn } from "../../components/ui/data-table"
import { DomainStatus } from "../../components/ui/domain-status"
import { ErrorText } from "../../components/ui/error-text"
import { DateRangePicker, EMPTY_RANGE, type DateRange } from "../../components/ui/date-range-picker"
import { Surface } from "../../components/ui/surface"
import { cn } from "../../lib/utils"
import { faDateTime, faNum } from "../../lib/dates"
import { adminApi, AdminSessionExpired } from "../api"
import { Retry } from "../useLive"

interface LogRow {
  id: string
  event: string
  level: string
  entity_type: string | null
  detail: Record<string, unknown> | null
  created_at: string
  organization_name: string | null
  actor_username: string | null
}

interface LogsPayload {
  total: number
  limit: number
  offset: number
  logs: LogRow[]
  server_log: { path: string | null; available: boolean; lines: string[] }
}

const LEVELS = [
  { id: "all", label: "همه" },
  { id: "activity", label: "فعالیت‌ها" },
  { id: "error", label: "خطاها" },
] as const

/**
 * The date filter goes to the server, not to the browser: the endpoint already
 * paginates, and filtering a page of 200 rows client-side would silently hide
 * matches that live on the next page.
 */
function rangeQuery(range: DateRange): string {
  let query = ""
  if (range.from) query += "&since=" + encodeURIComponent(range.from)
  if (range.to) query += "&until=" + encodeURIComponent(range.to)
  return query
}

/**
 * Events workspace.
 *
 * v0.1 filtered the audit trail with hand-rolled buttons, paginated with its own
 * previous/next pair, and printed the raw timestamp as an ISO slice — Gregorian,
 * Latin digits, in a Persian-first product. The shared DataTable owns sorting,
 * search, column control and CSV export, and the shared date layer renders
 * Jalali. [D15/A3]
 */
export default function EventsView({ token }: { token: string }) {
  const [level, setLevel] = useState<(typeof LEVELS)[number]["id"]>("all")
  const [range, setRange] = useState<DateRange>(EMPTY_RANGE)
  const [offset, setOffset] = useState(0)
  const [payload, setPayload] = useState<LogsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const limit = 200

  const load = useCallback(async () => {
    try {
      const data = await adminApi<LogsPayload>(
        token,
        "GET",
        "/logs?level=" + level + "&limit=" + limit + "&offset=" + offset + rangeQuery(range),
      )
      setPayload(data)
      setError(null)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      setError(err instanceof Error ? err.message : "دریافت رویدادها ناموفق بود.")
    }
  }, [token, level, offset, range])

  useEffect(() => {
    void load()
  }, [load])

  const columns: DataTableColumn<LogRow>[] = [
    {
      id: "created_at",
      header: "زمان",
      sortValue: (row) => row.created_at,
      cell: (row) => (
        <span data-numeric className="whitespace-nowrap text-muted-foreground">
          {faDateTime(row.created_at)}
        </span>
      ),
    },
    {
      id: "event",
      header: "رویداد",
      sortValue: (row) => row.event,
      searchValue: (row) => row.event,
      cell: (row) => (
        <div className="grid gap-0.5">
          <span className={cn("mono text-caption", row.level === "error" && "font-bold text-error")} dir="ltr">
            {row.event}
          </span>
          {row.detail && (
            <span className="mono truncate text-micro text-muted-foreground" dir="ltr">
              {JSON.stringify(row.detail)}
            </span>
          )}
        </div>
      ),
    },
    {
      id: "organization",
      header: "سازمان",
      sortValue: (row) => row.organization_name ?? "",
      searchValue: (row) => row.organization_name ?? "",
      cell: (row) => row.organization_name ?? "—",
    },
    {
      id: "actor",
      header: "کاربر",
      sortValue: (row) => row.actor_username ?? "",
      searchValue: (row) => row.actor_username ?? "",
      cell: (row) => (
        <span className={cn(!row.actor_username && "text-muted-foreground")} dir="ltr">
          {row.actor_username ?? "سامانه"}
        </span>
      ),
    },
    {
      id: "level",
      header: "سطح",
      sortValue: (row) => row.level,
      searchValue: (row) => row.level,
      hiddenByDefault: true,
      cell: (row) => <DomainStatus domain="severity" value={row.level} />,
    },
  ]

  if (error && !payload) return <Retry message={error} onRetry={() => void load()} />

  const total = payload?.total ?? 0

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {LEVELS.map((entry) => (
          <Button
            key={entry.id}
            variant={level === entry.id ? "default" : "outline"}
            size="sm"
            className="rounded-control"
            aria-pressed={level === entry.id}
            onClick={() => {
              setLevel(entry.id)
              setOffset(0)
            }}
          >
            {entry.label}
          </Button>
        ))}
        {/* Filtering by time is the question the audit trail exists to answer
            ("what changed last week"), and v0.1 could not ask it. [D15] */}
        <DateRangePicker
          value={range}
          onChange={(next) => {
            setRange(next)
            setOffset(0)
          }}
        />
        <span data-numeric className="ms-auto text-micro text-muted-foreground">
          {faNum(total)} رویداد
        </span>
      </div>

      <ErrorText>{error}</ErrorText>

      <DataTable
        rows={payload?.logs ?? []}
        columns={columns}
        rowKey={(row) => row.id}
        searchPlaceholder="جستجو در رویداد، سازمان یا کاربر…"
        exportName="hiveos-events"
        pageSize={25}
        density="compact"
        emptyIcon={ScrollTextIcon}
        emptyTitle="رویدادی با این فیلتر ثبت نشده است"
        emptyDescription="فیلتر سطح را تغییر دهید یا بازهٔ دیگری را بررسی کنید."
      />

      {total > limit && (
        <div className="flex items-center gap-3 text-caption">
          <Button
            variant="outline"
            size="sm"
            className="rounded-control"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            صفحهٔ قبل
          </Button>
          <span data-numeric className="text-muted-foreground">
            {faNum(offset + 1)}–{faNum(Math.min(offset + limit, total))} از {faNum(total)}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="rounded-control"
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
          >
            صفحهٔ بعد
          </Button>
        </div>
      )}

      {payload?.server_log?.available && (
        <Surface className="p-0">
          <details>
            <summary className="cursor-pointer px-4 py-3 text-caption font-bold">
              گزارش فایل سرور
            </summary>
            <pre
              dir="ltr"
              className="scrollbar-thin max-h-80 overflow-auto border-t border-border p-4 text-micro leading-relaxed"
            >
              {payload.server_log.lines.slice(-200).join("\n")}
            </pre>
          </details>
        </Surface>
      )}
    </div>
  )
}