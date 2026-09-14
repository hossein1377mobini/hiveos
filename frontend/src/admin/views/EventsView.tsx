import { useCallback, useEffect, useMemo, useState } from "react"
import { CopyIcon, ScrollTextIcon, SlidersHorizontalIcon, XIcon } from "lucide-react"

import { Button } from "../../components/ui/button"
import { DataTable, type DataTableColumn } from "../../components/ui/data-table"
import { DomainStatus } from "../../components/ui/domain-status"
import { ErrorText } from "../../components/ui/error-text"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "../../components/ui/sheet"
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
  entity_id: string | null
  detail: Record<string, unknown> | null
  created_at: string
  organization_id: string | null
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

interface Facet {
  value: string
  count: number
}

interface FacetsPayload {
  events: Facet[]
  actors: Facet[]
  organizations: Facet[]
}

const LEVELS = [
  { id: "all", label: "همه" },
  { id: "activity", label: "فعالیت‌ها" },
  { id: "error", label: "خطاها" },
] as const

type Level = (typeof LEVELS)[number]["id"]

/** "" is Radix Select's escape hatch for "no selection"; the API wants null. */
const ALL = "__all__"

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

/** One line summarising a detail object, for the table cell. */
function detailSummary(detail: Record<string, unknown> | null): string {
  if (!detail) return "—"
  const parts = Object.entries(detail).map(([key, value]) => {
    const text = typeof value === "string" ? value : JSON.stringify(value)
    return key + "=" + (text ?? "null")
  })
  return parts.join("  ")
}

/**
 * Events workspace.
 *
 * v0.1 filtered the audit trail with hand-rolled buttons, paginated with its own
 * previous/next pair, and printed the raw timestamp as an ISO slice — Gregorian,
 * Latin digits, in a Persian-first product. The shared DataTable owns sorting,
 * search, column control and CSV export, and the shared date layer renders
 * Jalali. [D15/A3]
 *
 * The PO asked for the panel's metrics — and the log in particular — to be much
 * more complete. Two things were structurally missing rather than merely thin:
 *
 *   1. Every filter was either a level toggle or a time range. An audit trail
 *      exists to answer "what did THIS actor do to THIS object", and there was
 *      no way to ask it. The exact-value filters below go to the server, so a
 *      filtered CSV export covers the whole matching set rather than one page.
 *   2. The columns the endpoint already returned (entity type/id, org id) were
 *      never rendered, so a row could not be traced back to the object it
 *      touched. They are columns now, and the row opens a full detail panel.
 */
export default function EventsView({ token }: { token: string }) {
  const [level, setLevel] = useState<Level>("all")
  const [range, setRange] = useState<DateRange>(EMPTY_RANGE)
  const [event, setEvent] = useState<string>(ALL)
  const [actor, setActor] = useState<string>(ALL)
  const [organization, setOrganization] = useState<string>(ALL)
  const [entityType, setEntityType] = useState<string>(ALL)
  const [onlyWithDetail, setOnlyWithDetail] = useState(false)
  const [offset, setOffset] = useState(0)
  const [payload, setPayload] = useState<LogsPayload | null>(null)
  const [facets, setFacets] = useState<FacetsPayload | null>(null)
  const [selected, setSelected] = useState<LogRow | null>(null)
  const [error, setError] = useState<string | null>(null)
  const limit = 200

  const filters = useMemo(
    () =>
      [
        level !== "all" && "level=" + level,
        event !== ALL && "event=" + encodeURIComponent(event),
        actor !== ALL && "actor_username=" + encodeURIComponent(actor),
        organization !== ALL && "organization_id=" + encodeURIComponent(organization),
        entityType !== ALL && "entity_type=" + encodeURIComponent(entityType),
        onlyWithDetail && "has_detail=true",
      ]
        .filter(Boolean)
        .join("&"),
    [level, event, actor, organization, entityType, onlyWithDetail],
  )

  const load = useCallback(async () => {
    try {
      const data = await adminApi<LogsPayload>(
        token,
        "GET",
        "/logs?" + filters + "&limit=" + limit + "&offset=" + offset + rangeQuery(range),
      )
      setPayload(data)
      setError(null)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      setError(err instanceof Error ? err.message : "دریافت رویدادها ناموفق بود.")
    }
  }, [token, filters, offset, range])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * Facets are refetched on level and range only, NOT on the facet selections
   * themselves. Narrowing by actor must not remove the other actors from the
   * dropdown, or the operator can never widen the filter again without clearing
   * everything.
   */
  const loadFacets = useCallback(async () => {
    try {
      const data = await adminApi<FacetsPayload>(
        token,
        "GET",
        "/logs/facets?level=" + level + rangeQuery(range),
      )
      setFacets(data)
    } catch (err) {
      // A missing facet list degrades to free-text filtering; it must not blank
      // the log itself.
      if (err instanceof AdminSessionExpired) return
      setFacets(null)
    }
  }, [token, level, range])

  useEffect(() => {
    void loadFacets()
  }, [loadFacets])

  const resetFilters = () => {
    setLevel("all")
    setRange(EMPTY_RANGE)
    setEvent(ALL)
    setActor(ALL)
    setOrganization(ALL)
    setEntityType(ALL)
    setOnlyWithDetail(false)
    setOffset(0)
  }

  const activeFilterCount =
    (level !== "all" ? 1 : 0) +
    (event !== ALL ? 1 : 0) +
    (actor !== ALL ? 1 : 0) +
    (organization !== ALL ? 1 : 0) +
    (entityType !== ALL ? 1 : 0) +
    (onlyWithDetail ? 1 : 0) +
    (range.from || range.to ? 1 : 0)

  const entityTypes = useMemo(() => {
    const seen = new Set<string>()
    for (const row of payload?.logs ?? []) {
      if (row.entity_type) seen.add(row.entity_type)
    }
    return [...seen].sort()
  }, [payload])

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
      id: "level",
      header: "سطح",
      sortValue: (row) => row.level,
      cell: (row) => <DomainStatus domain="severity" value={row.level} />,
    },
    {
      id: "event",
      header: "رویداد",
      sortValue: (row) => row.event,
      searchValue: (row) => row.event,
      cell: (row) => (
        <span
          className={cn("mono text-caption", row.level === "error" && "font-bold text-error")}
          dir="ltr"
        >
          {row.event}
        </span>
      ),
    },
    {
      id: "detail",
      header: "جزئیات",
      searchValue: (row) => detailSummary(row.detail),
      cell: (row) => (
        <span className="mono block max-w-[22rem] truncate text-micro text-muted-foreground" dir="ltr">
          {detailSummary(row.detail)}
        </span>
      ),
    },
    {
      id: "entity",
      header: "موجودیت",
      sortValue: (row) => row.entity_type ?? "",
      searchValue: (row) => row.entity_type ?? "",
      hiddenByDefault: true,
      cell: (row) =>
        row.entity_type ? (
          <span className="mono text-micro" dir="ltr">
            {row.entity_type}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
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
  ]

  if (error && !payload) return <Retry message={error} onRetry={() => void load()} />

  const total = payload?.total ?? 0

  /** A labelled server-side filter. Value "" means "no constraint". */
  const filterSelect = (
    label: string,
    value: string,
    onChange: (next: string) => void,
    options: Facet[],
    placeholder: string,
  ) => (
    <Select
      value={value}
      onValueChange={(next) => {
        onChange(next)
        setOffset(0)
      }}
    >
      <SelectTrigger className="h-9 w-auto min-w-[10rem] rounded-control" aria-label={label}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            <span className="mono" dir="ltr">
              {option.value}
            </span>
            <span data-numeric className="ms-2 text-micro text-muted-foreground">
              {faNum(option.count)}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

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

      {/* Exact-value filters, all server-side. The counts come from the facets
          endpoint over the whole matching set, not from the current page. */}
      <Surface className="flex flex-wrap items-center gap-2 p-3">
        <SlidersHorizontalIcon aria-hidden className="size-4 text-muted-foreground" />
        {filterSelect("رویداد", event, setEvent, facets?.events ?? [], "همهٔ رویدادها")}
        {filterSelect("کاربر", actor, setActor, facets?.actors ?? [], "همهٔ کاربران")}
        {filterSelect("سازمان", organization, setOrganization, facets?.organizations ?? [], "همهٔ سازمان‌ها")}
        <Select
          value={entityType}
          onValueChange={(next) => {
            setEntityType(next)
            setOffset(0)
          }}
        >
          <SelectTrigger className="h-9 w-auto min-w-[10rem] rounded-control" aria-label="نوع موجودیت">
            <SelectValue placeholder="همهٔ موجودیت‌ها" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>همهٔ موجودیت‌ها</SelectItem>
            {entityTypes.map((value) => (
              <SelectItem key={value} value={value}>
                <span className="mono" dir="ltr">
                  {value}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant={onlyWithDetail ? "default" : "outline"}
          size="sm"
          className="rounded-control"
          aria-pressed={onlyWithDetail}
          onClick={() => {
            setOnlyWithDetail((current) => !current)
            setOffset(0)
          }}
        >
          فقط دارای جزئیات
        </Button>
        {activeFilterCount > 0 && (
          <Button variant="ghost" size="sm" className="rounded-control" onClick={resetFilters}>
            <XIcon aria-hidden className="size-3.5" />
            پاک کردن {faNum(activeFilterCount)} فیلتر
          </Button>
        )}
      </Surface>

      <ErrorText>{error}</ErrorText>

      <DataTable
        rows={payload?.logs ?? []}
        columns={columns}
        rowKey={(row) => row.id}
        searchPlaceholder="جستجو در رویداد، سازمان، کاربر یا جزئیات…"
        exportName="hiveos-events"
        pageSize={25}
        density="compact"
        onRowClick={(row) => setSelected(row)}
        emptyIcon={ScrollTextIcon}
        emptyTitle="رویدادی با این فیلتر ثبت نشده است"
        emptyDescription="فیلترها را تغییر دهید یا بازهٔ دیگری را بررسی کنید."
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

      {/* Row detail. A Sheet rather than a dialog because the operator compares
          the row against the table behind it. */}
      <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent side="left" className="w-full overflow-y-auto sm:max-w-lg">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className="mono" dir="ltr">
                  {selected.event}
                </SheetTitle>
                <SheetDescription data-numeric>
                  {faDateTime(selected.created_at)}
                </SheetDescription>
              </SheetHeader>

              <div className="grid gap-3 px-4 pb-6 text-caption">
                <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2">
                  <dt className="text-muted-foreground">سطح</dt>
                  <dd>
                    <DomainStatus domain="severity" value={selected.level} />
                  </dd>
                  <dt className="text-muted-foreground">کاربر</dt>
                  <dd className="mono" dir="ltr">
                    {selected.actor_username ?? "سامانه"}
                  </dd>
                  <dt className="text-muted-foreground">سازمان</dt>
                  <dd>{selected.organization_name ?? "—"}</dd>
                  <dt className="text-muted-foreground">نوع موجودیت</dt>
                  <dd className="mono" dir="ltr">
                    {selected.entity_type ?? "—"}
                  </dd>
                  <dt className="text-muted-foreground">شناسهٔ موجودیت</dt>
                  <dd className="mono break-all text-micro" dir="ltr">
                    {selected.entity_id ?? "—"}
                  </dd>
                  <dt className="text-muted-foreground">شناسهٔ رویداد</dt>
                  <dd className="mono break-all text-micro" dir="ltr">
                    {selected.id}
                  </dd>
                </dl>

                <div className="flex items-center justify-between pt-2">
                  <span className="text-muted-foreground">جزئیات</span>
                  {selected.detail && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="rounded-control"
                      onClick={() => void navigator.clipboard?.writeText(JSON.stringify(selected.detail, null, 2))}
                    >
                      <CopyIcon aria-hidden className="size-3.5" />
                      کپی
                    </Button>
                  )}
                </div>
                <pre
                  dir="ltr"
                  className="scrollbar-thin max-h-72 overflow-auto rounded-control border border-border bg-neutral-25 p-3 text-micro leading-relaxed"
                >
                  {selected.detail ? JSON.stringify(selected.detail, null, 2) : "—"}
                </pre>

                {/* Pivot: the whole history of the object this row touched. This
                    is the question an audit trail is actually opened to answer. */}
                {selected.entity_type && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="justify-start rounded-control"
                    onClick={() => {
                      setEntityType(selected.entity_type!)
                      setSelected(null)
                      setOffset(0)
                    }}
                  >
                    نمایش همهٔ رویدادهای این نوع موجودیت
                  </Button>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
