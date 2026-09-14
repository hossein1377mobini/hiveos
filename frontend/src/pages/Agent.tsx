import { useCallback, useEffect, useState } from "react"
import { BotIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { api } from "../api/client"
import { Button } from "../components/ui/button"
import { EmptyState } from "../components/ui/empty-state"
import { ErrorText } from "../components/ui/error-text"
import { Skeleton } from "../components/ui/skeleton"
import { Surface } from "../components/ui/surface"
import { Textarea } from "../components/ui/textarea"
import { faDateTime, faNum } from "../lib/dates"

/**
 * «ایجنت من» — the user's own agent (PO 2026-09).
 *
 * Every user in an organization has their own agent with its own memory and
 * its own tool access. This page is where they see it and shape it: what it
 * has learned about them, what it is allowed to do, and what it has done.
 *
 * The persona field is the delicate one. It is *additive* to the
 * organization's grounding rules — the server appends it after them — so the
 * copy here says "لحن و ترجیحات" rather than "دستور". Telling a user they are
 * editing the system prompt would be false, and would invite them to try to
 * override the citation rules, which they cannot do.
 *
 * Transport goes through api(), not a local fetch: that is what carries the
 * Authorization header, the request timeout, and the 401 -> login redirect.
 */

interface AgentPayload {
  id: string
  display_name: string
  persona: string
  status: string
  version: number
  allowed_tools: string[]
  memory: {
    total: number
    by_kind: Record<string, { count: number; avg_weight: number }>
  }
}

interface MemoryRow {
  id: string
  kind: string
  content: string
  weight: number
  hits: number
  misses: number
  active: boolean
  created_at: string | null
}

interface ToolRow {
  name: string
  description: string
  enabled: boolean
  writes: boolean
}

const KIND_LABEL: Record<string, string> = {
  fact: "واقعیت",
  preference: "ترجیح",
  decision: "تصمیم",
  summary: "خلاصه",
}

export default function Agent() {
  const [agent, setAgent] = useState<AgentPayload | null>(null)
  const [memories, setMemories] = useState<MemoryRow[]>([])
  const [tools, setTools] = useState<ToolRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [agentData, memoryData, toolData] = await Promise.all([
        api<AgentPayload>("GET", "/agent"),
        api<{ memories: MemoryRow[] }>("GET", "/agent/memory"),
        api<{ tools: ToolRow[] }>("GET", "/agent/tools"),
      ])
      setAgent(agentData)
      setMemories(memoryData.memories)
      setTools(toolData.tools)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "دریافت اطلاعات ایجنت ناموفق بود.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading && !agent) {
    return (
      <div className="grid gap-4 p-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    )
  }

  if (error && !agent) {
    return (
      <div className="p-4">
        <ErrorText>{error}</ErrorText>
        <Button className="mt-3" variant="outline" onClick={() => void load()}>
          تلاش مجدد
        </Button>
      </div>
    )
  }

  if (!agent) return null

  return (
    <div className="mx-auto grid max-w-3xl gap-4 p-4">
      <header className="flex items-center gap-3">
        <BotIcon aria-hidden className="size-6 text-accent-600" />
        <div>
          <h1 className="text-title">ایجنت من</h1>
          <p className="text-caption text-muted-foreground">
            ایجنت اختصاصی شما؛ مستقل از سایر کاربران سازمان.
          </p>
        </div>
      </header>

      <PersonaCard
        key={agent.version}
        agent={agent}
        onSaved={(next) => setAgent(next)}
      />
      <ToolsCard
        tools={tools}
        allowlist={agent.allowed_tools}
        onSaved={(allowlist) => setAgent({ ...agent, allowed_tools: allowlist })}
      />
      <MemoryCard
        memories={memories}
        total={agent.memory.total}
        onChanged={() => void load()}
      />
    </div>
  )
}
function PersonaCard({
  agent,
  onSaved,
}: {
  agent: AgentPayload
  onSaved: (next: AgentPayload) => void
}) {
  const [displayName, setDisplayName] = useState(agent.display_name)
  const [persona, setPersona] = useState(agent.persona)
  const [busy, setBusy] = useState(false)

  const dirty = displayName !== agent.display_name || persona !== agent.persona

  async function save() {
    setBusy(true)
    try {
      const next = await api<AgentPayload>("PATCH", "/agent", {
        display_name: displayName,
        persona,
      })
      onSaved(next)
      toast.success("ذخیره شد.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "ذخیره ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Surface className="grid gap-3 p-4">
      <div>
        <h2 className="text-title">شناسنامه و لحن</h2>
        <p className="text-caption text-muted-foreground">
          این متن به قواعد پاسخ‌گویی سازمان اضافه می‌شود، نه اینکه جای آن را بگیرد.
        </p>
      </div>
      <label className="grid gap-1.5">
        <span className="text-caption text-muted-foreground">نام نمایشی</span>
        <input
          className="h-9 w-full rounded-control border border-border bg-card px-3 text-caption"
          value={displayName}
          maxLength={120}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="مثلاً دستیار فروش من"
        />
        <span className="text-micro text-muted-foreground">
          اختیاری؛ فقط برای نمایش در همین صفحه.
        </span>
      </label>
      <label className="grid gap-1.5">
        <span className="text-caption text-muted-foreground">لحن و ترجیحات</span>
        <Textarea
          value={persona}
          maxLength={4000}
          rows={5}
          onChange={(event) => setPersona(event.target.value)}
          placeholder="مثلاً همیشه کوتاه و رسمی پاسخ بده…"
        />
      </label>
      <div className="flex items-center gap-3">
        <Button onClick={() => void save()} disabled={busy || !dirty}>
          {busy ? "در حال ذخیره…" : "ذخیره"}
        </Button>
        <span className="text-micro text-muted-foreground">نسخهٔ {faNum(agent.version)}</span>
      </div>
    </Surface>
  )
}

function ToolsCard({
  tools,
  allowlist,
  onSaved,
}: {
  tools: ToolRow[]
  allowlist: string[]
  onSaved: (allowlist: string[]) => void
}) {
  // An empty allowlist means "everything", matching the server. Presenting
  // that as "nothing enabled" would make a fresh agent look broken.
  const [enabled, setEnabled] = useState<Set<string>>(
    () => new Set(allowlist.length === 0 ? tools.map((tool) => tool.name) : allowlist),
  )
  const [busy, setBusy] = useState(false)

  function toggle(name: string) {
    setEnabled((current) => {
      const next = new Set(current)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  async function save() {
    setBusy(true)
    try {
      const result = await api<{ allowlist: string[] }>("PATCH", "/agent/tools", {
        allowed_tools: [...enabled],
      })
      onSaved(result.allowlist)
      toast.success("ابزارها ذخیره شد.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "ذخیره ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Surface className="grid gap-3 p-4">
      <div>
        <h2 className="text-title">ابزارها</h2>
        <p className="text-caption text-muted-foreground">
          ایجنت برای ساخت نمودار و گزارش از این ابزارها استفاده می‌کند.
        </p>
      </div>
      <ul className="grid gap-2">
        {tools.map((tool) => (
          <li
            key={tool.name}
            className="flex items-start gap-3 rounded-control border border-border px-3 py-2"
          >
            <input
              id={"tool-" + tool.name}
              type="checkbox"
              className="mt-1 size-4"
              checked={enabled.has(tool.name)}
              onChange={() => toggle(tool.name)}
            />
            <label htmlFor={"tool-" + tool.name} className="grid gap-0.5">
              <span className="text-caption text-foreground">
                {tool.name === "build_chart"
                  ? "ساخت نمودار"
                  : tool.name === "build_report"
                    ? "ساخت گزارش"
                    : tool.name}
              </span>
              <span className="text-micro text-muted-foreground">{tool.description}</span>
            </label>
          </li>
        ))}
      </ul>
      <div>
        <Button onClick={() => void save()} disabled={busy}>
          {busy ? "در حال ذخیره…" : "ذخیرهٔ ابزارها"}
        </Button>
      </div>
    </Surface>
  )
}
function MemoryCard({
  memories,
  total,
  onChanged,
}: {
  memories: MemoryRow[]
  total: number
  onChanged: () => void
}) {
  const [busyId, setBusyId] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [adding, setAdding] = useState(false)

  async function forget(id: string) {
    setBusyId(id)
    try {
      await api("DELETE", "/agent/memory/" + id)
      toast.success("فراموش شد.")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "حذف ناموفق بود.")
    } finally {
      setBusyId(null)
    }
  }

  async function add() {
    const content = draft.trim()
    if (!content) return
    setAdding(true)
    try {
      await api("POST", "/agent/memory", { content, kind: "fact" })
      setDraft("")
      toast.success("به حافظه اضافه شد.")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "افزودن ناموفق بود.")
    } finally {
      setAdding(false)
    }
  }

  return (
    <Surface className="grid gap-3 p-4">
      <div>
        <h2 className="text-title">حافظه</h2>
        <p className="text-caption text-muted-foreground">
          چیزهایی که ایجنت از گفتگوهای شما به خاطر سپرده است. هر موردی را
          می‌توانید حذف کنید.
        </p>
      </div>

      <div className="grid gap-2">
        <Textarea
          aria-label="افزودن به حافظه"
          value={draft}
          rows={2}
          maxLength={600}
          placeholder="چیزی که می‌خواهید ایجنت همیشه بداند…"
          onChange={(event) => setDraft(event.target.value)}
        />
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void add()}
            disabled={adding || !draft.trim()}
          >
            {adding ? "در حال افزودن…" : "افزودن به حافظه"}
          </Button>
        </div>
      </div>

      {memories.length === 0 ? (
        <EmptyState
          icon={BotIcon}
          title="هنوز چیزی به خاطر نسپرده"
          description="با هر گفتگو، ترجیح‌ها و تصمیم‌های شما ذخیره می‌شود."
        />
      ) : (
        <ul className="grid gap-2">
          {memories.map((memory) => (
            <li
              key={memory.id}
              className="flex items-start gap-3 rounded-control border border-border px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-micro text-muted-foreground">
                  <span className="rounded-pill bg-secondary px-2 py-0.5">
                    {KIND_LABEL[memory.kind] ?? memory.kind}
                  </span>
                  <span className="mono">
                    {memory.created_at ? faDateTime(memory.created_at) : ""}
                  </span>
                </div>
                <p className="mt-1 text-caption text-foreground">{memory.content}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                aria-label="حذف این خاطره"
                disabled={busyId === memory.id}
                onClick={() => void forget(memory.id)}
              >
                <Trash2Icon aria-hidden className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      {total > memories.length && (
        <p className="text-micro text-muted-foreground">
          {faNum(memories.length)} مورد از {faNum(total)} مورد نمایش داده شده است.
        </p>
      )}
    </Surface>
  )
}