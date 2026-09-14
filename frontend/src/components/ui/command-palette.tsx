import * as React from "react"
import { useNavigate } from "react-router-dom"
import { CornerDownLeftIcon, SearchIcon } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { norm } from "@/lib/dates"

/**
 * Global command palette (Ctrl/⌘+K). [D2/D7]
 *
 * v0.1 had no cross-surface navigation at all: reaching «اشتراک» from «گفتگو»
 * meant clicking the sidebar, and reaching anything inside the admin panel meant
 * clicking a flat tab strip. A keyboard-first jump list is the standard
 * enterprise answer, and it is also the only affordance that scales once the
 * sidebar grows with the Hive Pulse and Hive Flow sections.
 */
export interface CommandItem {
  id: string
  label: string
  /** Grouping heading, e.g. «هوش سازمان» or «پنل مدیریت». */
  group: string
  keywords?: string[]
  icon?: React.ComponentType<{ className?: string }>
  /** Router path. Omit for a pure action. */
  path?: string
  /** Runs before navigation — used for actions such as «خروج». */
  onSelect?: () => void
}

export function CommandPalette({
  items,
  open,
  onOpenChange,
}: {
  items: CommandItem[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const [query, setQuery] = React.useState("")
  const [active, setActive] = React.useState(0)
  const listRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!open) {
      setQuery("")
      setActive(0)
    }
  }, [open])

  const filtered = React.useMemo(() => {
    const q = norm(query)
    if (!q) return items
    return items.filter((item) =>
      [item.label, item.group, ...(item.keywords ?? [])].some((value) => norm(value).includes(q)),
    )
  }, [items, query])

  // Group while preserving the order the caller declared.
  const groups = React.useMemo(() => {
    const map = new Map<string, CommandItem[]>()
    for (const item of filtered) {
      const bucket = map.get(item.group)
      if (bucket) bucket.push(item)
      else map.set(item.group, [item])
    }
    return [...map.entries()]
  }, [filtered])

  const flat = React.useMemo(() => groups.flatMap(([, group]) => group), [groups])
  const safeActive = flat.length === 0 ? 0 : Math.min(active, flat.length - 1)

  function run(item: CommandItem) {
    onOpenChange(false)
    item.onSelect?.()
    if (item.path) navigate(item.path)
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setActive(Math.min(safeActive + 1, flat.length - 1))
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setActive(Math.max(safeActive - 1, 0))
    } else if (event.key === "Enter") {
      event.preventDefault()
      const item = flat[safeActive]
      if (item) run(item)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[12%] max-w-xl translate-y-0 gap-0 overflow-hidden p-0"
        aria-label="جستجوی سراسری"
      >
        <DialogTitle className="sr-only">جستجوی سراسری</DialogTitle>
        <DialogDescription className="sr-only">
          برای پرش بین بخش‌ها یا اجرای فرمان، تایپ کنید و با کلیدهای جهت‌دار انتخاب کنید.
        </DialogDescription>

        <div className="flex items-center gap-2.5 border-b border-border px-3.5">
          <SearchIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
            placeholder="جستجو در بخش‌ها و فرمان‌ها…"
            aria-label="جستجوی سراسری"
            className="h-12 w-full bg-transparent text-body outline-none placeholder:text-muted-foreground"
          />
          <kbd className="mono shrink-0 rounded-xs border border-border bg-secondary px-1.5 py-0.5 text-micro text-muted-foreground">
            Esc
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-1.5">
          {flat.length === 0 && (
            <p className="px-3 py-8 text-center text-caption text-muted-foreground">
              نتیجه‌ای برای «{query}» پیدا نشد.
            </p>
          )}
          {groups.map(([group, groupItems]) => (
            <div key={group} className="mb-1">
              <p className="px-2.5 py-1.5 text-micro font-bold text-muted-foreground">{group}</p>
              {groupItems.map((item) => {
                const index = flat.indexOf(item)
                const isActive = index === safeActive
                const Icon = item.icon
                return (
                  <button
                    key={item.id}
                    type="button"
                    onMouseEnter={() => setActive(index)}
                    onClick={() => run(item)}
                    aria-current={isActive ? "true" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-start text-caption transition-colors",
                      isActive ? "bg-accent text-accent-foreground" : "text-foreground hover:bg-secondary",
                    )}
                  >
                    {Icon ? (
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <span aria-hidden className="size-4 shrink-0" />
                    )}
                    <span className="flex-1 truncate font-medium">{item.label}</span>
                    {isActive && <CornerDownLeftIcon aria-hidden className="size-3.5 text-muted-foreground" />}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Wires the Ctrl/⌘+K shortcut and returns the palette element.
 * Mounted once per shell so both the app and the admin panel get it.
 */
export function useCommandPalette() {
  const [open, setOpen] = React.useState(false)

  React.useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setOpen((current) => !current)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  return { open, setOpen }
}
