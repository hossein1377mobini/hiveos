import { useCallback, useEffect, useState } from "react"
import { InboxIcon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "../../components/ui/button"
import { ConfirmDialog } from "../../components/ui/confirm-dialog"
import { EmptyState } from "../../components/ui/empty-state"
import { DomainStatus } from "../../components/ui/domain-status"
import { Surface } from "../../components/ui/surface"
import { faNum } from "../../lib/dates"
import { adminApi, AdminSessionExpired } from "../api"
import { freshInputTokens, readUsage, usdText, type UserUsage } from "../OrgDetailPanel"
import { Section } from "../page-layout"
import { Retry } from "../useLive"

interface ChargeRequestItem {
  id: string
  organization_id: string
  organization_name?: string | null
  amount: number
  status: string
  note: string | null
  created_at?: string | null
}

/**
 * The organisation's consumption, summed from the per-user usage blocks of
 * GET /admin/organizations/{id} (backend/backend/admin.py:organization_detail).
 * The detail payload carries usage per member, not one organisation total, so
 * adding the members is the only honest way to get the org figure - and the
 * label says as much. A failed lookup leaves null rather than a fake zero.
 */
function sumUsage(users: Array<Record<string, unknown>>): UserUsage {
  const total: UserUsage = {
    executions: 0,
    tokens_in: 0,
    tokens_out: 0,
    cached_tokens: 0,
    reasoning_tokens: 0,
    cost_usd: 0,
    cost_credits: 0,
  }
  for (const user of users) {
    const usage = readUsage(user.usage)
    if (!usage) continue
    total.executions += usage.executions
    total.tokens_in += usage.tokens_in
    total.tokens_out += usage.tokens_out
    total.cached_tokens += usage.cached_tokens
    total.reasoning_tokens += usage.reasoning_tokens
    total.cost_usd += usage.cost_usd
    total.cost_credits += usage.cost_credits
  }
  return total
}

/**
 * Billing workspace.
 *
 * Approving a charge request moves money into an organisation's wallet and v0.1
 * did it on a single click with no confirmation and no record of who decided
 * what or why. Both decisions are confirmed with a reason now. [D6/D16]
 */
export default function BillingView({ token }: { token: string }) {
  const [items, setItems] = useState<ChargeRequestItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [target, setTarget] = useState<{ item: ChargeRequestItem; approve: boolean } | null>(null)
  /** organisation_id -> its summed usage, null when the lookup failed. */
  const [orgUsage, setOrgUsage] = useState<Record<string, UserUsage | null>>({})

  const load = useCallback(async () => {
    try {
      const data = await adminApi<{ requests: ChargeRequestItem[] }>(token, "GET", "/charge-requests")
      setItems(data.requests ?? [])
      setError(null)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      setError(err instanceof Error ? err.message : "دریافت درخواست‌ها ناموفق بود.")
    }
  }, [token])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * The org-level usage/cost summary for every organisation with a pending
   * request: approving credit is a consumption decision, so the operator needs
   * to see what that organisation has already consumed. Any org already in
   * orgUsage is skipped, so this settles instead of re-fetching on every render.
   */
  useEffect(() => {
    const ids = [
      ...new Set(items.filter((item) => item.status === "PENDING").map((item) => item.organization_id)),
    ].filter((id) => !(id in orgUsage))
    if (ids.length === 0) return
    let cancelled = false
    void (async () => {
      for (const id of ids) {
        try {
          const detail = await adminApi<{ users?: Array<Record<string, unknown>> }>(
            token,
            "GET",
            "/organizations/" + id,
          )
          if (cancelled) return
          setOrgUsage((prev) => ({ ...prev, [id]: sumUsage(detail.users ?? []) }))
        } catch (err) {
          if (cancelled || err instanceof AdminSessionExpired) return
          setOrgUsage((prev) => ({ ...prev, [id]: null }))
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [items, token, orgUsage])

  async function decide(reason: string) {
    if (!target) return
    const { item, approve } = target
    setBusy(true)
    try {
      await adminApi(token, "POST", "/charge-requests/" + item.id + "/decision", { approve, reason })
      toast.success(approve ? "درخواست تأیید شد" : "درخواست رد شد", {
        description: approve
          ? faNum(item.amount) + " واحد اعتبار به کیف پول سازمان افزوده شد."
          : "دلیل رد در رویدادهای سامانه ثبت شد.",
      })
      setTarget(null)
      await load()
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      toast.error(err instanceof Error ? err.message : "ثبت تصمیم ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  const pending = items.filter((item) => item.status === "PENDING")
  const decided = items.filter((item) => item.status !== "PENDING")

  if (error && items.length === 0) return <Retry message={error} onRetry={() => void load()} />

  return (
    <div className="grid gap-5">
      <Section
        title={
          <>
            در انتظار تصمیم
            {pending.length > 0 && (
              <span data-numeric className="ms-2 text-micro font-normal text-muted-foreground">
                ({faNum(pending.length)})
              </span>
            )}
          </>
        }
      >
        {pending.length === 0 ? (
          <EmptyState
            icon={InboxIcon}
            title="درخواست شارژ در انتظاری نیست"
            description="درخواست تازه‌ای که سازمان‌ها ثبت کنند، همین‌جا برای تصمیم‌گیری نمایش داده می‌شود."
          />
        ) : (
          pending.map((item) => (
            <Surface key={item.id} className="flex flex-wrap items-center justify-between gap-4">
              <div className="grid gap-1">
                <span className="text-body font-bold">
                  {item.organization_name ?? item.organization_id}
                </span>
                <span data-numeric className="text-caption text-muted-foreground">
                  درخواست {faNum(item.amount)} واحد اعتبار
                </span>
                {/*
                  Org-level consumption/cost summary, the admin half of the
                  PO's «میزان مصرف هر کاربر»: token classes, USD cost and the
                  credits deducted, summed over this organisation's members. A
                  failed lookup stays silent rather than printing a zero that
                  would read as "this organisation consumed nothing".
                */}
                {orgUsage[item.organization_id] && (
                  <span
                    className="text-micro text-muted-foreground"
                    data-testid={"org-usage-" + item.organization_id}
                  >
                    مصرف سازمان تاکنون:{" "}
                    <span data-numeric>{faNum(freshInputTokens(orgUsage[item.organization_id]!))}</span> ورودی تازه ·{" "}
                    <span data-numeric>{faNum(orgUsage[item.organization_id]!.cached_tokens)}</span> کش‌شده ·{" "}
                    <span data-numeric>{faNum(orgUsage[item.organization_id]!.tokens_out)}</span> خروجی ·{" "}
                    <span dir="ltr" data-numeric>{usdText(orgUsage[item.organization_id]!.cost_usd)}</span> ·{" "}
                    <span data-numeric>{faNum(orgUsage[item.organization_id]!.cost_credits)}</span> اعتبار
                  </span>
                )}
                {item.note && (
                  <span className="text-caption text-muted-foreground">یادداشت: {item.note}</span>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  className="rounded-control"
                  onClick={() => setTarget({ item, approve: true })}
                >
                  تأیید و افزودن اعتبار
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-control text-error"
                  onClick={() => setTarget({ item, approve: false })}
                >
                  رد درخواست
                </Button>
              </div>
            </Surface>
          ))
        )}
      </Section>

      {decided.length > 0 && (
        <Section title="تصمیم‌های پیشین">
          <Surface className="p-0">
            <ul className="divide-y divide-border">
              {decided.map((item) => (
                <li key={item.id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="min-w-0 flex-1 truncate text-caption">
                    {item.organization_name ?? item.organization_id}
                  </span>
                  <span data-numeric className="text-caption text-muted-foreground">
                    {faNum(item.amount)}
                  </span>
                  <DomainStatus domain="charge" value={item.status} />
                </li>
              ))}
            </ul>
          </Surface>
        </Section>
      )}

      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => !open && setTarget(null)}
        level="critical"
        title={target?.approve ? "تأیید درخواست شارژ" : "رد درخواست شارژ"}
        description={
          target?.approve ? (
            <>
              <b data-numeric>{faNum(target.item.amount)}</b> واحد اعتبار به کیف پول سازمان «
              <b>{target.item.organization_name ?? target.item.organization_id}</b>» افزوده می‌شود.
            </>
          ) : (
            <>
              درخواست <b data-numeric>{faNum(target?.item.amount ?? 0)}</b> واحدی سازمان «
              <b>{target?.item.organization_name ?? target?.item.organization_id}</b>» رد می‌شود.
            </>
          )
        }
        consequences={
          target?.approve
            ? [
                "این مبلغ از این پس در گفتگوها قابل مصرف است.",
                "موجودی کیف پول سازمان بلافاصله تغییر می‌کند.",
              ]
            : ["اعتباری افزوده نمی‌شود.", "دلیل رد برای پیگیری‌های بعدی ثبت می‌ماند."]
        }
        confirmLabel={target?.approve ? "تأیید و افزودن" : "رد درخواست"}
        busy={busy}
        onConfirm={({ reason }) => void decide(reason)}
      />
    </div>
  )
}