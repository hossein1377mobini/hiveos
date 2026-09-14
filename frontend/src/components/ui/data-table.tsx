import * as React from "react"
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Columns3Icon,
  DownloadIcon,
  SearchIcon,
} from "lucide-react"

import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

/**
 * The product's single data table. [D10/D14]
 *
 * v0.1 rendered raw <Table> markup in four places with hand-written headers and
 * no sorting, no filtering, no column control, no pagination and no export.
 * Admins work on lists of organizations, events and documents all day; those
 * are the operations that make that work fast, so they live here once.
 */
export interface DataTableColumn<T> {
  id: string
  header: string
  /** Cell renderer. Receives the row and its index. */
  cell: (row: T, index: number) => React.ReactNode
  /** Sort key. Return a primitive; omit to make the column unsortable. */
  sortValue?: (row: T) => string | number | null | undefined
  /** Text used by the built-in search box. Omit to exclude from search. */
  searchValue?: (row: T) => string
  /** Default hidden — the operator can turn it back on from the column menu. */
  hiddenByDefault?: boolean
  align?: "start" | "end" | "center"
  headClassName?: string
  cellClassName?: string
  /** Right-align numbers and add tabular figures automatically. */
  numeric?: boolean
}

export interface DataTableProps<T> {
  rows: T[]
  columns: DataTableColumn<T>[]
  rowKey: (row: T) => string
  /** Search placeholder. Pass null to hide the search box entirely. */
  searchPlaceholder?: string | null
  loading?: boolean
  /** Rows per page. Pass 0 to disable pagination. */
  pageSize?: number
  emptyTitle?: string
  emptyDescription?: React.ReactNode
  emptyAction?: React.ReactNode
  emptyIcon?: LucideIcon
  /** Toolbar content placed before the search box. */
  toolbar?: React.ReactNode
  /** Extra per-row content, e.g. a detail drawer. */
  onRowClick?: (row: T) => void
  /** File name stem used by the CSV export button. Null hides the button. */
  exportName?: string | null
  className?: string
  /** Density. Compact tightens rows for data-heavy admin views. */
  density?: "comfortable" | "compact"
}

type SortState = { id: string; dir: "asc" | "desc" } | null

function compare(a: string | number | null | undefined, b: string | number | null | undefined): number {
  const av = a ?? ""
  const bv = b ?? ""
  if (typeof av === "number" && typeof bv === "number") return av - bv
  return String(av).localeCompare(String(bv), "fa")
}

function toCsv<T>(rows: T[], columns: DataTableColumn<T>[]): string {
  const escape = (value: unknown): string => {
    const text = value === null || value === undefined ? "" : String(value)
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text
  }
  const head = columns.map((c) => escape(c.header)).join(",")
  const body = rows.map((row) => columns.map((c) => escape(c.searchValue?.(row) ?? "")).join(","))
  return [head, ...body].join("\n")
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  searchPlaceholder = "جستجو…",
  loading = false,
  pageSize = 25,
  emptyTitle = "چیزی برای نمایش نیست",
  emptyDescription,
  emptyAction,
  emptyIcon,
  toolbar,
  onRowClick,
  exportName = null,
  className,
  density = "comfortable",
}: DataTableProps<T>) {
  const [query, setQuery] = React.useState("")
  const [sort, setSort] = React.useState<SortState>(null)
  const [page, setPage] = React.useState(0)
  const [hidden, setHidden] = React.useState<Set<string>>(
    () => new Set(columns.filter((c) => c.hiddenByDefault).map((c) => c.id)),
  )

  // Any change to the query or the sort must return the operator to page one;
  // staying on page 5 of a result set that now has two pages shows an empty
  // table and reads as a bug.
  React.useEffect(() => {
    setPage(0)
  }, [query, sort, rows.length])

  const visible = columns.filter((c) => !hidden.has(c.id))

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((row) =>
      columns.some((column) => column.searchValue?.(row)?.toLowerCase().includes(q)),
    )
  }, [rows, columns, query])

  const sorted = React.useMemo(() => {
    if (!sort) return filtered
    const column = columns.find((c) => c.id === sort.id)
    if (!column?.sortValue) return filtered
    const next = [...filtered].sort((a, b) => compare(column.sortValue!(a), column.sortValue!(b)))
    return sort.dir === "asc" ? next : next.reverse()
  }, [filtered, sort, columns])

  const pageCount = pageSize > 0 ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1
  const safePage = Math.min(page, pageCount - 1)
  const paged = pageSize > 0 ? sorted.slice(safePage * pageSize, safePage * pageSize + pageSize) : sorted

  function toggleSort(column: DataTableColumn<T>) {
    if (!column.sortValue) return
    setSort((current) => {
      if (!current || current.id !== column.id) return { id: column.id, dir: "asc" }
      if (current.dir === "asc") return { id: column.id, dir: "desc" }
      return null
    })
  }

  function download() {
    const csv = "\uFEFF" + toCsv(sorted, visible)
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = (exportName ?? "export") + ".csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  const cellPad = density === "compact" ? "px-3 py-1.5" : "px-3 py-2.5"

  return (
    <div className={cn("flex min-w-0 flex-col gap-3", className)}>
      {(toolbar || searchPlaceholder || exportName || columns.length > 1) && (
        <div className="flex flex-wrap items-center gap-2">
          {toolbar}
          {searchPlaceholder && (
            <div className="relative min-w-[200px] flex-1">
              <SearchIcon
                aria-hidden
                className="pointer-events-none absolute inset-y-0 start-2.5 my-auto size-3.5 text-muted-foreground"
              />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                className="h-9 rounded-control ps-8 text-caption"
              />
            </div>
          )}
          <div className="ms-auto flex items-center gap-2">
            {columns.length > 1 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="rounded-control" aria-label="انتخاب ستون‌ها">
                    <Columns3Icon className="size-3.5" />
                    ستون‌ها
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-[180px]">
                  <DropdownMenuLabel className="text-micro text-muted-foreground">نمایش ستون‌ها</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {columns.map((column) => (
                    <DropdownMenuCheckboxItem
                      key={column.id}
                      checked={!hidden.has(column.id)}
                      onCheckedChange={(checked) => {
                        setHidden((current) => {
                          const next = new Set(current)
                          if (checked) next.delete(column.id)
                          else next.add(column.id)
                          return next
                        })
                      }}
                      onSelect={(event) => event.preventDefault()}
                    >
                      {column.header}
                    </DropdownMenuCheckboxItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            {exportName && sorted.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                className="rounded-control"
                onClick={download}
                aria-label="خروجی CSV"
              >
                <DownloadIcon className="size-3.5" />
                خروجی
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <Table>
          <TableHeader>
            <TableRow className="border-border bg-neutral-25 hover:bg-neutral-25">
              {visible.map((column) => {
                const active = sort?.id === column.id
                const sortable = Boolean(column.sortValue)
                return (
                  <TableHead
                    key={column.id}
                    className={cn(
                      "h-10 px-3 text-micro font-bold text-muted-foreground",
                      column.align === "end" && "text-end",
                      column.align === "center" && "text-center",
                      column.headClassName,
                    )}
                    aria-sort={active ? (sort!.dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(column)}
                        className="inline-flex items-center gap-1 rounded-xs transition-colors hover:text-foreground"
                      >
                        {column.header}
                        {active &&
                          (sort!.dir === "asc" ? (
                            <ArrowUpIcon className="size-3" />
                          ) : (
                            <ArrowDownIcon className="size-3" />
                          ))}
                      </button>
                    ) : (
                      column.header
                    )}
                  </TableHead>
                )
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && paged.length === 0 && (
              <TableRow>
                <TableCell colSpan={visible.length} className="h-24 text-center text-caption text-muted-foreground">
                  در حال دریافت…
                </TableCell>
              </TableRow>
            )}
            {!loading && paged.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={visible.length} className="p-0">
                  <EmptyState
                    icon={emptyIcon}
                    title={emptyTitle}
                    description={emptyDescription}
                    action={emptyAction}
                    className="border-0 bg-transparent"
                  />
                </TableCell>
              </TableRow>
            )}
            {paged.map((row, index) => (
              <TableRow
                key={rowKey(row)}
                className={cn("border-border", onRowClick && "cursor-pointer")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {visible.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn(
                      cellPad,
                      "text-caption",
                      column.numeric && "text-end",
                      column.align === "end" && "text-end",
                      column.align === "center" && "text-center",
                      column.cellClassName,
                    )}
                  >
                    {column.cell(row, index)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {pageSize > 0 && sorted.length > pageSize && (
        <div className="flex items-center justify-between gap-3 text-micro text-muted-foreground">
          <span data-numeric>
            {safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, sorted.length)} از{" "}
            {sorted.length}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              className="rounded-control"
              onClick={() => setPage(Math.max(0, safePage - 1))}
              disabled={safePage === 0}
              aria-label="صفحهٔ قبل"
            >
              <ChevronRightIcon className="size-4" />
            </Button>
            <span data-numeric className="px-2 font-bold text-foreground">
              {safePage + 1} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="icon-sm"
              className="rounded-control"
              onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))}
              disabled={safePage >= pageCount - 1}
              aria-label="صفحهٔ بعد"
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
