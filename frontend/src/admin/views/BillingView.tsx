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
      <section className="grid gap-3">
        <h2 className="text-subheading">
          در انتظار تصمیم
          {pending.length > 0 && (
            <span data-numeric className="ms-2 text-micro font-normal text-muted-foreground">
              ({faNum(pending.length)})
            </span>
          )}
        </h2>
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
      </section>

      {decided.length > 0 && (
        <section className="grid gap-3">
          <h2 className="text-subheading">تصمیم‌های پیشین</h2>
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
        </section>
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