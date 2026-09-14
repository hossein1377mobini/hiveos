import { useCallback, useEffect, useState } from "react"
import { BuildingIcon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "../../components/ui/button"
import { ConfirmDialog } from "../../components/ui/confirm-dialog"
import { DataTable, type DataTableColumn } from "../../components/ui/data-table"
import { Input } from "../../components/ui/input"
import { DomainStatus } from "../../components/ui/domain-status"
import { Surface } from "../../components/ui/surface"
import { faDateTime, faNum, norm } from "../../lib/dates"
import { adminApi, AdminSessionExpired } from "../api"
import { Retry } from "../useLive"
import { OrgDetailPanel, type OrgDetail } from "../OrgDetailPanel"

export interface Org {
  id: string
  name: string
  status: string
  balance: number
  plan?: string
  plan_expires_at?: string | null
  industry?: string | null
  size?: string | null
  created_at?: string
  users?: number
  assets?: number
  chat_sessions?: number
  executions?: number
  last_activity_at?: string | null
}

/**
 * Organizations workspace.
 *
 * v0.1 rendered every organisation as a row of raw markup with an inline credit
 * input and a destructive delete button, and gated both irreversible actions on
 * window.confirm / window.prompt. Those cannot be styled, cannot record a reason
 * and cannot be tested. Actions that move money or destroy an account now go
 * through ConfirmDialog, which requires a written reason for the ledger and a
 * typed phrase for deletion. [D5/D6/D16]
 */
export default function OrganizationsView({ token }: { token: string }) {
  const [orgs, setOrgs] = useState<Org[]>([])
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<OrgDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /** Pending destructive action awaiting confirmation. */
  const [creditTarget, setCreditTarget] = useState<{ org: Org; amount: number } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Org | null>(null)
  const [removeUserTarget, setRemoveUserTarget] = useState<
    { org: Org; userId: string; username: string } | null
  >(null)

  const load = useCallback(async () => {
    try {
      const data = await adminApi<{ organizations: Org[] }>(token, "GET", "/organizations")
      setOrgs(data.organizations ?? [])
      setError(null)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      setError(err instanceof Error ? err.message : "دریافت فهرست سازمان‌ها ناموفق بود.")
    }
  }, [token])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = useCallback(
    async (id: string) => {
      setOpenId(id)
      setDetail(null)
      setDetailError(null)
      try {
        setDetail(await adminApi<OrgDetail>(token, "GET", "/organizations/" + id))
      } catch (err) {
        if (err instanceof AdminSessionExpired) return
        setDetailError(err instanceof Error ? err.message : "دریافت جزئیات سازمان ناموفق بود.")
      }
    },
    [token],
  )

  async function confirmCredit(reason: string) {
    if (!creditTarget) return
    const { org, amount } = creditTarget
    setBusy(true)
    try {
      await adminApi(token, "POST", "/organizations/" + org.id + "/credit", { amount, reason })
      toast.success("اعتبار افزوده شد", { description: org.name + " — " + faNum(amount) + " واحد" })
      setCreditTarget(null)
      await load()
      if (openId === org.id) await openDetail(org.id)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      toast.error(err instanceof Error ? err.message : "افزودن اعتبار ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  async function confirmDelete(reason: string) {
    if (!deleteTarget) return
    const org = deleteTarget
    setBusy(true)
    try {
      const result = await adminApi<{ removed_users: number }>(
        token,
        "DELETE",
        "/organizations/" + org.id,
        { reason },
      )
      toast.success("سازمان حذف شد", {
        description: (result.removed_users ?? 0) + " کاربر آزاد شد؛ ثبت‌نام دوباره ممکن است.",
      })
      setDeleteTarget(null)
      setOpenId(null)
      setDetail(null)
      await load()
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      toast.error(err instanceof Error ? err.message : "حذف سازمان ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  async function confirmRemoveUser(reason: string) {
    if (!removeUserTarget) return
    const { org, userId, username } = removeUserTarget
    setBusy(true)
    try {
      const result = await adminApi<{ account_removed: boolean }>(
        token,
        "DELETE",
        "/organizations/" + org.id + "/users/" + userId,
        { reason },
      )
      toast.success("کاربر حذف شد", {
        description: result.account_removed
          ? "حساب «" + username + "» هم حذف شد."
          : "«" + username + "» از این سازمان حذف شد (حسابش در سازمان دیگری باقی است).",
      })
      setRemoveUserTarget(null)
      await load()
      if (openId === org.id) await openDetail(org.id)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      toast.error(err instanceof Error ? err.message : "حذف کاربر ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  const columns: DataTableColumn<Org>[] = [
    {
      id: "name",
      header: "سازمان",
      sortValue: (o) => o.name,
      searchValue: (o) => [o.name, o.industry ?? "", o.plan ?? ""].join(" "),
      cell: (o) => (
        <div className="flex min-w-0 flex-col gap-0.5">
          <button
            type="button"
            className="cursor-pointer truncate text-start font-bold text-primary hover:underline"
            onClick={() => void openDetail(o.id)}
          >
            {o.name}
          </button>
          <span data-numeric className="text-micro text-muted-foreground">
            {o.created_at ? "ساخت " + faDateTime(o.created_at) : "—"}
          </span>
        </div>
      ),
    },
    {
      id: "status",
      header: "وضعیت",
      sortValue: (o) => o.status,
      searchValue: (o) => o.status,
      cell: (o) => <DomainStatus domain="organization" value={o.status} />,
    },
    {
      id: "balance",
      header: "موجودی",
      numeric: true,
      sortValue: (o) => o.balance,
      cell: (o) => (
        <span data-numeric data-testid={"balance-" + o.id} className="font-bold">
          {faNum(o.balance)}
        </span>
      ),
    },
    {
      id: "usage",
      header: "کاربران / اسناد",
      numeric: true,
      sortValue: (o) => o.users ?? 0,
      cell: (o) => (
        <span data-numeric className="text-muted-foreground">
          {faNum(o.users ?? 0)} / {faNum(o.assets ?? 0)}
        </span>
      ),
    },
    {
      id: "plan",
      header: "پلن",
      sortValue: (o) => o.plan ?? "",
      searchValue: (o) => o.plan ?? "",
      cell: (o) => (
        <div className="flex flex-col gap-0.5">
          <span>{o.plan ?? "آزمایشی"}</span>
          {o.plan_expires_at && (
            <span data-numeric className="text-micro text-muted-foreground">
              تا {faDateTime(o.plan_expires_at)}
            </span>
          )}
        </div>
      ),
    },
    {
      id: "actions",
      header: "عملیات",
      align: "end",
      cell: (o) => <RowActions org={o} onCredit={setCreditTarget} onDelete={setDeleteTarget} />,
    },
  ]

  if (error) return <Retry message={error} onRetry={() => void load()} />

  return (
    <div className="grid gap-5">
      <DataTable
        rows={orgs}
        columns={columns}
        rowKey={(o) => o.id}
        searchPlaceholder="جستجوی سازمان، صنعت یا پلن…"
        exportName="hiveos-organizations"
        emptyIcon={BuildingIcon}
        emptyTitle="سازمانی ثبت نشده است"
        emptyDescription="به‌محض ثبت‌نام نخستین سازمان، فهرست آن اینجا نمایش داده می‌شود."
      />

      {openId && (
        <Surface className="p-5" aria-label="جزئیات سازمان">
          <h2 className="text-heading">جزئیات سازمان</h2>
          {detailError && (
            <div className="mt-3">
              <Retry message={detailError} onRetry={() => void openDetail(openId)} />
            </div>
          )}
          {!detail && !detailError && (
            <p className="mt-3 text-caption text-muted-foreground">در حال بارگذاری…</p>
          )}
          {detail && (
            <OrgDetailPanel
              detail={detail}
              busy={busy}
              onSetQuota={async (value) => {
                const orgId = String(detail.organization.id)
                setBusy(true)
                try {
                  await adminApi(token, "PUT", "/organizations/" + orgId + "/storage-quota", {
                    storage_quota_mb: value,
                  })
                  toast.success("سقف فضا ذخیره شد")
                  await openDetail(orgId)
                } catch (err) {
                  if (err instanceof AdminSessionExpired) return
                  toast.error(err instanceof Error ? err.message : "ذخیرهٔ سقف فضا ناموفق بود.")
                } finally {
                  setBusy(false)
                }
              }}
              onRemoveUser={(userId, username) => {
                const org = orgs.find((o) => o.id === openId)
                if (org) setRemoveUserTarget({ org, userId, username })
              }}
            />
          )}
        </Surface>
      )}

      <CreditDialog
        target={creditTarget}
        busy={busy}
        onOpenChange={(open) => !open && setCreditTarget(null)}
        onConfirm={confirmCredit}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        level="paranoid"
        title="حذف کامل سازمان"
        description={
          <>
            سازمان «<b>{deleteTarget?.name}</b>» و همهٔ داده‌های آن برای همیشه حذف می‌شود.
          </>
        }
        consequences={[
          "همهٔ اسناد، گفتگوها و سوابق کیف پول این سازمان حذف می‌شود.",
          (deleteTarget?.users ?? 0) + " کاربر این سازمان حذف می‌شوند.",
          "همین کاربر می‌تواند دوباره با همان شماره ثبت‌نام کند.",
        ]}
        confirmPhrase={deleteTarget?.name}
        confirmLabel="حذف برای همیشه"
        busy={busy}
        onConfirm={({ reason }) => void confirmDelete(reason)}
      />

      <ConfirmDialog
        open={removeUserTarget !== null}
        onOpenChange={(open) => !open && setRemoveUserTarget(null)}
        level="critical"
        title="حذف کاربر از سازمان"
        description={
          <>
            کاربر «<b dir="ltr">{removeUserTarget?.username}</b>» از سازمان «
            {removeUserTarget?.org.name}» حذف می‌شود و دیگر به اسناد و گفتگوهای آن دسترسی ندارد.
          </>
        }
        confirmLabel="حذف کاربر"
        busy={busy}
        onConfirm={({ reason }) => void confirmRemoveUser(reason)}
      />
    </div>
  )
}

/**
 * Row actions.
 *
 * The inline credit input of v0.1 sat in every row, so the table carried a
 * permanent text field and a permanent delete button next to ordinary
 * information. Both actions open a dialog now, which also lets the operator see
 * the amount and the organisation together before committing. [D16]
 */
function RowActions({
  org,
  onCredit,
  onDelete,
}: {
  org: Org
  onCredit: (target: { org: Org; amount: number }) => void
  onDelete: (org: Org) => void
}) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState("")

  const parsed = Number(norm(amount))
  const valid = Number.isFinite(parsed) && parsed > 0

  if (!open) {
    return (
      <div className="flex items-center justify-end gap-1.5">
        <Button
          variant="outline"
          size="sm"
          className="rounded-control"
          onClick={() => setOpen(true)}
        >
          افزودن اعتبار
        </Button>
        <Button
          variant="ghost"
          size="sm"
          aria-label={"حذف سازمان " + org.name}
          className="rounded-control text-error hover:bg-error-bg hover:text-error"
          onClick={() => onDelete(org)}
        >
          حذف
        </Button>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-end gap-1.5">
      <Input
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        inputMode="numeric"
        aria-label={"مبلغ اعتبار برای " + org.name}
        placeholder="مثلاً ۵۰۰"
        className="h-8 w-28 text-caption"
        autoFocus
        onKeyDown={(event) => {
          if (event.key === "Enter" && valid) {
            onCredit({ org, amount: parsed })
            setOpen(false)
          }
          if (event.key === "Escape") setOpen(false)
        }}
      />
      <Button
        size="sm"
        className="rounded-control"
        disabled={!valid}
        onClick={() => {
          onCredit({ org, amount: parsed })
          setOpen(false)
        }}
      >
        ادامه
      </Button>
      <Button variant="ghost" size="sm" className="rounded-control" onClick={() => setOpen(false)}>
        انصراف
      </Button>
    </div>
  )
}

/** Money confirmation: the amount and the recipient, then a required reason. */
function CreditDialog({
  target,
  busy,
  onOpenChange,
  onConfirm,
}: {
  target: { org: Org; amount: number } | null
  busy: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (reason: string) => void
}) {
  return (
    <ConfirmDialog
      open={target !== null}
      onOpenChange={onOpenChange}
      level="critical"
      title="افزودن اعتبار به کیف پول"
      description={
        <>
          <b data-numeric>{faNum(target?.amount ?? 0)}</b> واحد اعتبار به سازمان «
          <b>{target?.org.name}</b>» افزوده می‌شود.
        </>
      }
      consequences={[
        "این مبلغ در دفتر کل کیف پول سازمان ثبت می‌شود و قابل بازگردانی نیست.",
        "موجودی فعلی " + faNum(target?.org.balance ?? 0) + " واحد است.",
        "دلیل ثبت‌شده در رویدادهای سامانه باقی می‌ماند.",
      ]}
      confirmLabel="افزودن اعتبار"
      busy={busy}
      onConfirm={({ reason }) => onConfirm(reason)}
    />
  )
}