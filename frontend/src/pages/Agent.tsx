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
 * The agent answers on the organization's behalf, so how it behaves is an
 * organization decision, not a personal preference. Persona, the tool
 * allowlist and the memory-ranking knobs all live in the admin panel's "agent"
 * setting, next to the prompt template they are merged with — the PO's point
 * was exactly that the persona and the AI answer settings are not separate
 * things. PATCH /agent/tools is refused with
 * AGENT_SETTINGS_MANAGED_BY_ORGANIZATION, and PATCH /agent now accepts only
 * display_name (extra="forbid"), so a persona control here would be a control
 * the server rejects.
 *
 * What is left is what genuinely belongs to the person: the name they call
 * their assistant, the memories it learned about them, and the trace of what
 * it did. Nothing on this page renders a control the server would refuse — a
 * dead textarea is worse than no textarea.
 *
 * GET /agent/tools is read-only and carries managed_by "organization" plus
 * unrestricted, so the tool list is presented as the organization's policy
 * rather than as this user's own choice.
 *
 * Transport goes through api(), not a local fetch: that is what carries the
 * Authorization header, the request timeout, and the 401 -> login redirect.
 */

interface AgentPayload {
  id: string
  display_name: string
  status: string
  version: number
  /**
   * Still returned by GET /agent, but no longer editable here: the persona in
   * force is the organization's, and the tool allowlist is reported through
   * GET /agent/tools. Kept on the type so the contract stays documented.
   */
  persona: string
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

/** GET /agent/tools — the catalogue plus the organization's decision on it. */
interface ToolsPayload {
  tools: ToolRow[]
  allowlist: string[]
  /** True when the allowlist is empty, which the server reads as "every tool". */
  unrestricted: boolean
  /** Always "organization" today; the page keys its wording off it. */
  managed_by: string
}

const KIND_LABEL: Record<string, string> = {
  fact: "واقعیت",
  preference: "ترجیح",
  decision: "تصمیم",
  summary: "خلاصه",
}

const TOOL_LABEL: Record<string, string> = {
  build_chart: "ساخت نمودار",
  build_report: "ساخت گزارش",
}

export default function Agent() {
  const [agent, setAgent] = useState<AgentPayload | null>(null)
  const [memories, setMemories] = useState<MemoryRow[]>([])
  const [toolPolicy, setToolPolicy] = useState<ToolsPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [agentData, memoryData, toolData] = await Promise.all([
        api<AgentPayload>("GET", "/agent"),
        api<{ memories: MemoryRow[] }>("GET", "/agent/memory"),
        api<ToolsPayload>("GET", "/agent/tools"),
      ])
      setAgent(agentData)
      setMemories(memoryData.memories)
      setToolPolicy(toolData)
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

      <NameCard key={agent.version} agent={agent} onSaved={(next) => setAgent(next)} />
      <PersonaPolicyCard />
      <ToolsPolicyCard policy={toolPolicy} />
      <MemoryCard
        memories={memories}
        total={agent.memory.total}
        onChanged={() => void load()}
      />
    </div>
  )
}

/**
 * The one field the user still owns on the agent itself. PATCH /agent takes
 * {display_name} and nothing else, so the payload is exactly that one key.
 */
function NameCard({
  agent,
  onSaved,
}: {
  agent: AgentPayload
  onSaved: (next: AgentPayload) => void
}) {
  const [displayName, setDisplayName] = useState(agent.display_name)
  const [busy, setBusy] = useState(false)

  const dirty = displayName !== agent.display_name

  async function save() {
    setBusy(true)
    try {
      const next = await api<AgentPayload>("PATCH", "/agent", {
        display_name: displayName,
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
        <h2 className="text-heading">نام دستیار</h2>
        <p className="text-caption text-muted-foreground">
          فقط نامی که شما این دستیار را با آن صدا می‌زنید.
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
      <div className="flex items-center gap-3">
        <Button onClick={() => void save()} disabled={busy || !dirty}>
          {busy ? "در حال ذخیره…" : "ذخیره"}
        </Button>
        <span className="text-micro text-muted-foreground">نسخهٔ {faNum(agent.version)}</span>
      </div>
    </Surface>
  )
}

/**
 * Where the persona editor used to be. Deliberately prose, not a disabled
 * textarea: the field is not the user's to set, and a greyed-out control reads
 * as "you are missing a permission" rather than "this is an organization
 * decision". The copy also states the precedence — a persona is appended to
 * the organization's grounding rules and can never displace them.
 */
function PersonaPolicyCard() {
  return (
    <Surface className="grid gap-2 p-4">
      <h2 className="text-heading">لحن و شخصیت</h2>
      <p className="text-caption leading-relaxed text-muted-foreground">
        لحن و شخصیت دستیار برای همهٔ کاربران سازمان یکسان است. مدیر سازمان آن را در
        پنل مدیریت، همراه با تنظیمات پاسخ‌دهی هوش مصنوعی، تعیین می‌کند؛ این دو از هم
        جدا نیستند، چون هر دو در یک پاسخ اثر می‌گذارند.
      </p>
      <p className="text-micro leading-relaxed text-muted-foreground">
        این لحن به قواعد پاسخ‌گویی سازمان اضافه می‌شود و جای آن‌ها را نمی‌گیرد؛
        نمی‌تواند قواعد استناد و ارجاع را کنار بزند. حافظهٔ پایین همین صفحه
        شخصیِ شماست و فقط از گفتگوهای خودتان ساخته می‌شود.
      </p>
    </Surface>
  )
}

/**
 * Read-only on purpose. PATCH /agent/tools always answers 403 with
 * AGENT_SETTINGS_MANAGED_BY_ORGANIZATION, so the page reports the decision
 * instead of offering to change it. An empty allowlist means "every tool", so
 * it is stated as such — presenting it as "nothing enabled" would make a
 * fresh toolbox look broken.
 */
function ToolsPolicyCard({ policy }: { policy: ToolsPayload | null }) {
  if (!policy) return null

  return (
    <Surface className="grid gap-3 p-4">
      <div>
        <h2 className="text-heading">ابزارهای فعال</h2>
        <p className="text-caption leading-relaxed text-muted-foreground">
          {policy.unrestricted
            ? "مدیر سازمان همهٔ ابزارهای موجود را برای ایجنت شما فعال کرده است."
            : "مدیر سازمان فقط بخشی از ابزارها را برای ایجنت شما فعال کرده است؛ فهرست زیر همان تصمیم است."}
        </p>
      </div>
      <ul className="grid gap-2">
        {policy.tools.map((tool) => (
          <li
            key={tool.name}
            className="flex items-start gap-3 rounded-control border border-border px-3 py-2"
          >
            <span
              className={
                tool.enabled
                  ? "mt-0.5 shrink-0 text-micro text-success"
                  : "mt-0.5 shrink-0 text-micro text-muted-foreground"
              }
            >
              {tool.enabled ? "فعال" : "غیرفعال"}
            </span>
            <div className="grid gap-0.5">
              <span className="text-caption text-foreground">
                {TOOL_LABEL[tool.name] ?? tool.name}
              </span>
              <span className="text-micro text-muted-foreground">{tool.description}</span>
            </div>
          </li>
        ))}
      </ul>
      {policy.managed_by === "organization" && (
        <p className="text-micro text-muted-foreground">
          تغییر این فهرست در پنل مدیریت، بخش «تنظیمات ایجنت سازمان»، انجام می‌شود و
          برای همهٔ کاربران سازمان اعمال می‌شود.
        </p>
      )}
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
        <h2 className="text-heading">حافظه</h2>
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
