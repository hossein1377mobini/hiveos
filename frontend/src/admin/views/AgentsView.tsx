import { useCallback, useState } from "react"
import { BotIcon, ChevronLeftIcon, RefreshCwIcon } from "lucide-react"

import { Button } from "../../components/ui/button"
import { Surface } from "../../components/ui/surface"
import { EmptyState } from "../../components/ui/empty-state"
import { BarChart, KpiTile } from "../../components/ui/chart"
import { faDateTime, faNum } from "../../lib/dates"
import { LoadingPanel, SectionHeading } from "../page-layout"
import { Retry, useLive } from "../useLive"

/**
 * Agents workspace (PO 2026-09).
 *
 * The product ships one agent per user. The organization view counts seats,
 * not agents, so "how many agents exist and are they working" is not
 * answerable there — this is the view for the fleet itself.
 *
 * Two levels: the fleet, then one agent in full. The detail level is where a
 * "my agent remembers something wrong" report gets resolved, because it shows
 * the memories with their weights and hit counts rather than the answer text.
 *
 * Polls every 30s. The overview runs four aggregate queries, and agent memory
 * only changes on chat turns, so a tighter interval would buy nothing.
 *
 * Persona and the tool allowlist are NOT this agent's own settings any more.
 * They are the organization-wide "agent" setting, and the admin detail here
 * reads columns off the row, which still hold whatever a user set before the
 * contract changed. So the detail panel labels them as policy in force and
 * says where they are actually edited, rather than presenting a stale column
 * as if it were the user's live choice. The memory list and the invocation
 * trace stay exactly as they were: those are genuinely per-user.
 *
 * Section headings are h2, not h3: the shell already renders the workspace
 * name as the page h1, and skipping to h3 is a heading-order violation.
 */

const POLL_MS = 30_000

interface AgentRow {
  id: string
  organization_id: string
  organization_name: string | null
  user_id: string
  username: string | null
  display_name: string
  status: string
  version: number
  allowed_tools: string[]
  memory_count: number
  active_memory_count: number
  tool_calls: number
  tool_failures: number
  last_tool_at: string | null
  last_active_at: string | null
  created_at: string | null
}

interface AgentsPayload {
  agents: AgentRow[]
  totals: { agents: number; active: number; organizations: number }
}

interface MemoryRow {
  id: string
  kind: string
  content: string
  weight: number
  active: boolean
  hits: number
  misses: number
  created_at: string | null
}

interface ToolStat {
  tool_name: string
  calls: number
  failures: number
  avg_ms: number | null
  max_ms: number | null
}

interface InvocationRow {
  id: string
  tool_name: string
  ok: boolean
  duration_ms: number
  round_index: number
  asset_id: string | null
  error_message: string | null
  created_at: string | null
}

interface AgentDetailPayload {
  agent: {
    id: string
    organization_name: string | null
    username: string | null
    display_name: string
    /**
     * Both of these are the row's stored columns, not a statement of current
     * policy: the persona the runtime uses comes from the organization setting
     * and the allowlist is reported by GET /agent/tools. Displayed as "what is
     * in force and where it is set", never as something this user chose.
     */
    persona: string
    allowed_tools: string[]
    status: string
    version: number
    last_active_at: string | null
    created_at: string | null
  }
  memories: MemoryRow[]
  tools: ToolStat[]
  recent_invocations: InvocationRow[]
}

const STATUS_LABEL: Record<string, string> = {
  active: "فعال",
  paused: "موقتاً متوقف",
  archived: "بایگانی",
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

/** A user is identified by username, then display name, then a short id —
 * never an empty cell, which reads as a rendering bug. */
function agentLabel(row: { username: string | null; display_name: string; id: string }) {
  return row.username || row.display_name || row.id.slice(0, 8)
}

export default function AgentsView({ token }: { token: string }) {
  const [selected, setSelected] = useState<string | null>(null)
  if (selected) {
    return <AgentDetail token={token} agentId={selected} onBack={() => setSelected(null)} />
  }
  return <AgentFleet token={token} onSelect={setSelected} />
}

function AgentFleet({
  token,
  onSelect,
}: {
  token: string
  onSelect: (id: string) => void
}) {
  const { data, error, loading, reload } = useLive<AgentsPayload>(token, "/agents", POLL_MS)
  const refresh = useCallback(() => {
    void reload()
  }, [reload])

  if (loading && !data) return <LoadingPanel label="در حال دریافت ایجنت‌ها…" />
  if (error && !data) return <Retry message={error} onRetry={refresh} />
  if (!data) return null

  const { totals, agents } = data
  // Chart the busiest agents, not all of them: 300 bars is a wall, and the
  // question this answers is "who is actually using it".
  const busiest = [...agents]
    .filter((row) => row.tool_calls > 0)
    .sort((a, b) => b.tool_calls - a.tool_calls)
    .slice(0, 8)
    .map((row) => ({ label: agentLabel(row), value: row.tool_calls }));

  return (
    <div className="grid gap-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <KpiTile label="ایجنت‌ها" value={faNum(totals.agents)} />
        <KpiTile label="فعال" value={faNum(totals.active)} tone="success" />
        <KpiTile label="سازمان‌های دارای ایجنت" value={faNum(totals.organizations)} />
      </div>

      {busiest.length > 0 && (
        <Surface className="p-4">
          <SectionHeading className="mb-3">پرکارترین ایجنت‌ها</SectionHeading>
          <BarChart data={busiest} valueLabel="فراخوانی" />
        </Surface>
      )}

      <Surface className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <SectionHeading>فهرست ایجنت‌ها</SectionHeading>
          <Button variant="ghost" size="sm" onClick={refresh}>
            <RefreshCwIcon aria-hidden className="size-4" />
            <span className="ms-1.5">به‌روزرسانی</span>
          </Button>
        </div>
        {agents.length === 0 ? (
          <EmptyState
            icon={BotIcon}
            title="هنوز ایجنتی ساخته نشده"
            description="ایجنت هر کاربر وقتی ساخته می‌شود که برای اولین بار وارد بخش گفتگو شود."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-caption">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th scope="col" className="px-4 py-2 text-start font-medium">کاربر</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">سازمان</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">وضعیت</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">حافظهٔ فعال</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">فراخوانی ابزار</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">آخرین فعالیت</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((row) => (
                  <tr key={row.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        className="text-start text-foreground underline-offset-2 hover:underline"
                        onClick={() => onSelect(row.id)}
                      >
                        {agentLabel(row)}
                      </button>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {row.organization_name || "—"}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {STATUS_LABEL[row.status] ?? row.status}
                    </td>
                    <td data-numeric className="mono px-4 py-2 text-muted-foreground">
                      {faNum(row.active_memory_count)} از {faNum(row.memory_count)}
                    </td>
                    <td data-numeric className="mono px-4 py-2 text-muted-foreground">
                      {faNum(row.tool_calls)}
                      {row.tool_failures > 0 && (
                        <span className="text-error"> ({faNum(row.tool_failures)} خطا)</span>
                      )}
                    </td>
                    <td className="mono px-4 py-2 text-muted-foreground">
                      {row.last_active_at ? faDateTime(row.last_active_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Surface>
    </div>
  )
}
function AgentDetail({
  token,
  agentId,
  onBack,
}: {
  token: string
  agentId: string
  onBack: () => void
}) {
  const { data, error, loading, reload } = useLive<AgentDetailPayload>(
    token,
    `/agents/${agentId}`,
    POLL_MS,
  )
  const refresh = useCallback(() => {
    void reload()
  }, [reload])

  return (
    <div className="grid gap-5">
      <div>
        <Button variant="ghost" size="sm" onClick={onBack} className="-ms-2 mb-2">
          <ChevronLeftIcon aria-hidden className="size-4 rotate-180" />
          <span className="ms-1">بازگشت به فهرست</span>
        </Button>
        {loading && !data ? (
          <LoadingPanel label="در حال دریافت ایجنت…" />
        ) : error && !data ? (
          <Retry message={error} onRetry={refresh} />
        ) : data ? (
          <Surface className="p-4">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <SectionHeading>
                {agentLabel({ ...data.agent, id: agentId })}
              </SectionHeading>
              <span className="text-caption text-muted-foreground">
                {data.agent.organization_name || "—"}
              </span>
              <span className="mono text-caption text-muted-foreground">
                نسخهٔ {faNum(data.agent.version)}
              </span>
            </div>
            <dl className="mt-3 grid gap-2 text-caption sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">وضعیت</dt>
                <dd className="text-muted-foreground">
                  {STATUS_LABEL[data.agent.status] ?? data.agent.status}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">آخرین فعالیت</dt>
                <dd className="mono text-muted-foreground">
                  {data.agent.last_active_at ? faDateTime(data.agent.last_active_at) : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">ابزارهای مجاز (سیاست سازمان)</dt>
                <dd className="text-muted-foreground">
                  {data.agent.allowed_tools.length === 0
                    ? "همهٔ ابزارها"
                    : data.agent.allowed_tools.map((name) => TOOL_LABEL[name] ?? name).join("، ")}
                </dd>
              </div>
            </dl>
            <div className="mt-3 border-t border-border pt-3">
              <h3 className="text-caption font-bold text-muted-foreground">
                سیاست سازمانی در جریان
              </h3>
              <p className="mt-1 text-micro leading-relaxed text-muted-foreground">
                شخصیت و فهرست ابزارهای دستیار برای همهٔ کاربران سازمان یکسان است و
                مدیر سازمان آن را در پنل مدیریت، در «تنظیمات ایجنت سازمان» — همراه با
                تنظیمات پاسخ‌دهی هوش مصنوعی — تعیین می‌کند. آنچه اینجا می‌بینید همان
                تصمیم سازمانی است، نه تنظیم شخصی این کاربر؛ چیزی که برای این ایجنت
                جداگانه قابل تغییر نیست.
              </p>
              {data.agent.persona && (
                <div className="mt-3">
                  <div className="text-caption text-muted-foreground">
                    شخصیت ثبت‌شده برای این ایجنت
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-caption text-muted-foreground">
                    {data.agent.persona}
                  </p>
                </div>
              )}
            </div>
          </Surface>
        ) : null}
      </div>

      {data && data.tools.length > 0 && (
        <Surface className="p-4">
          <SectionHeading className="mb-3">کاربرد ابزارها</SectionHeading>
          <div className="overflow-x-auto">
            <table className="w-full text-caption">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th scope="col" className="px-3 py-2 text-start font-medium">ابزار</th>
                  <th scope="col" className="px-3 py-2 text-start font-medium">فراخوانی</th>
                  <th scope="col" className="px-3 py-2 text-start font-medium">خطا</th>
                  <th scope="col" className="px-3 py-2 text-start font-medium">میانگین (ms)</th>
                  <th scope="col" className="px-3 py-2 text-start font-medium">بیشینه (ms)</th>
                </tr>
              </thead>
              <tbody>
                {data.tools.map((row) => (
                  <tr key={row.tool_name} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 text-foreground">
                      {TOOL_LABEL[row.tool_name] ?? row.tool_name}
                    </td>
                    <td data-numeric className="mono px-3 py-2 text-muted-foreground">
                      {faNum(row.calls)}
                    </td>
                    <td data-numeric className="mono px-3 py-2 text-muted-foreground">
                      {row.failures > 0 ? (
                        <span className="text-error">{faNum(row.failures)}</span>
                      ) : (
                        faNum(0)
                      )}
                    </td>
                    <td data-numeric className="mono px-3 py-2 text-muted-foreground">
                      {faNum(row.avg_ms ?? 0)}
                    </td>
                    <td data-numeric className="mono px-3 py-2 text-muted-foreground">
                      {faNum(row.max_ms ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>
      )}

      <Surface className="p-4">
        <SectionHeading className="mb-3">حافظهٔ ایجنت</SectionHeading>
        {!data ? null : data.memories.length === 0 ? (
          <EmptyState
            title="حافظهٔ این ایجنت خالی است"
            description="با هر گفتگو، ایجنت ترجیح‌ها و تصمیم‌های کاربر را به خاطر می‌سپارد."
          />
        ) : (
          <ul className="grid gap-2">
            {data.memories.map((memory) => (
              <li key={memory.id} className="rounded-control border border-border px-3 py-2">
                <div className="flex flex-wrap items-center gap-2 text-caption">
                  <span className="rounded-pill bg-secondary px-2 py-0.5 text-muted-foreground">
                    {KIND_LABEL[memory.kind] ?? memory.kind}
                  </span>
                  {!memory.active && <span className="text-muted-foreground">غیرفعال</span>}
                  <span className="mono text-muted-foreground">
                    وزن {memory.weight.toFixed(2)} · {faNum(memory.hits)} برد · 
                    {faNum(memory.misses)} باخت
                  </span>
                </div>
                <p className="mt-1 text-caption text-muted-foreground">{memory.content}</p>
              </li>
            ))}
          </ul>
        )}
      </Surface>

      {data && data.recent_invocations.length > 0 && (
        <Surface className="p-4">
          <SectionHeading className="mb-3">آخرین فراخوانی‌ها</SectionHeading>
          <ul className="grid gap-1">
            {data.recent_invocations.map((row) => (
              <li
                key={row.id}
                className="mono flex flex-wrap items-center gap-2 border-b border-border py-1.5 text-caption last:border-0"
              >
                <span className={row.ok ? "text-success" : "text-error"}>
                  {row.ok ? "OK" : "FAIL"}
                </span>
                <span className="text-foreground">
                  {TOOL_LABEL[row.tool_name] ?? row.tool_name}
                </span>
                <span className="text-muted-foreground">{faNum(row.duration_ms)}ms</span>
                <span className="text-muted-foreground">دور {faNum(row.round_index + 1)}</span>
                {row.asset_id && <span className="text-muted-foreground">فایل ساخته شد</span>}
                <span className="ms-auto text-muted-foreground">
                  {row.created_at ? faDateTime(row.created_at) : ""}
                </span>
              </li>
            ))}
          </ul>
        </Surface>
      )}
    </div>
  )
}