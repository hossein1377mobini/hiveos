import { useState } from "react"
import { FileTextIcon, UsersIcon } from "lucide-react"

import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { DomainStatus } from "../components/ui/domain-status"
import { faDateTime, faNum, humanSize, norm } from "../lib/dates"

export interface OrgDetail {
  organization: Record<string, unknown>
  users: Array<Record<string, unknown>>
  wallet_transactions: Array<Record<string, unknown>>
  charge_requests: Array<Record<string, unknown>>
  recent_events: Array<Record<string, unknown>>
  assets_by_status: Record<string, number>
  knowledge_source: Record<string, unknown> | null
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-muted-foreground">{label}</dt>
      <dd className="truncate text-caption font-bold text-foreground">{value}</dd>
    </div>
  )
}

/**
 * Organisation detail.
 *
 * v0.1 printed the raw asset-status map as "key: n · key: n" — an internal enum
 * leaked straight to the operator — and rendered every date as an ISO slice, so
 * the panel showed Gregorian dates in a Persian-first product. Values are
 * translated and Jalali-formatted now. [D4/D15]
 */
export function OrgDetailPanel({
  detail,
  busy,
  onSetQuota,
  onRemoveUser,
}: {
  detail: OrgDetail
  busy?: boolean
  onSetQuota?: (value: number | null) => void
  onRemoveUser?: (userId: string, username: string) => void
  quotaSaved?: boolean
}) {
  const org = detail.organization
  const counters = detail.assets_by_status ?? {}
  // The input is seeded from the server value, but the operator's own edit wins
  // until the server answers. v0.1 used a useState initializer, which ran once:
  // the panel is not remounted after a save (the organization id is unchanged),
  // so the field kept the pre-save text while every other fact refreshed.
  //
  // Derived rather than synchronised in an effect: an effect would render the
  // stale value first and correct it on a second pass.
  const storedQuota =
    org.storage_quota_mb === null || org.storage_quota_mb === undefined
      ? ""
      : String(org.storage_quota_mb)
  const [quotaEdit, setQuotaEdit] = useState<{ from: string; text: string } | null>(null)
  const quotaDraft = quotaEdit && quotaEdit.from === storedQuota ? quotaEdit.text : storedQuota
  const setQuotaDraft = (text: string) => setQuotaEdit({ from: storedQuota, text })

  const quotaMb = org.storage_quota_mb === null || org.storage_quota_mb === undefined
    ? null
    : Number(org.storage_quota_mb)
  const usedBytes = Number(org.storage_bytes ?? 0)
  const quotaBytes = quotaMb === null ? null : quotaMb * 1024 * 1024
  const usedPercent = quotaBytes && quotaBytes > 0 ? Math.min(100, (usedBytes / quotaBytes) * 100) : null

  return (
    <div className="mt-4 grid gap-6">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-4">
        <Fact label="صنعت" value={String(org.industry ?? "—")} />
        <Fact label="اندازه" value={String(org.size ?? "—")} />
        <Fact label="مدیر" value={<span dir="ltr">{String(org.owner_username ?? "—")}</span>} />
        <Fact label="موجودی" value={<span data-numeric>{faNum(Number(org.balance ?? 0))}</span>} />
        <Fact label="پلن" value={String(org.plan ?? "آزمایشی")} />
        <Fact label="انقضای پلن" value={<span data-numeric>{faDateTime(org.plan_expires_at as string)}</span>} />
        <Fact label="وضعیت" value={<DomainStatus domain="organization" value={String(org.status ?? "")} />} />
        <Fact label="تاریخ ساخت" value={<span data-numeric>{faDateTime(org.created_at as string)}</span>} />
      </dl>

      <section className="grid gap-2">
        <h3 className="text-subheading">فضای ذخیره‌سازی</h3>
        <p className="text-caption text-muted-foreground">
          مصرف فعلی: <span data-numeric>{humanSize(usedBytes)}</span>
          {quotaMb === null
            ? " — بدون سقف"
            : " از " + faNum(quotaMb) + " مگابایت"}
        </p>
        {usedPercent !== null && (
          <div
            role="progressbar"
            aria-valuenow={Math.round(usedPercent)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="میزان مصرف فضای سازمان"
            className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
          >
            <div
              className={
                "h-full rounded-full " +
                (usedPercent >= 90 ? "bg-error" : usedPercent >= 70 ? "bg-warning" : "bg-success")
              }
              style={{ width: usedPercent + "%" }}
            />
          </div>
        )}
        {onSetQuota && (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Input
              type="number"
              min={1}
              className="h-9 w-32 text-caption"
              aria-label="سقف فضای ذخیره‌سازی به مگابایت"
              value={quotaDraft}
              placeholder="بی‌سقف"
              onChange={(event) => setQuotaDraft(event.target.value)}
            />
            <span className="text-caption text-muted-foreground">مگابایت</span>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              data-testid="save-quota"
              className="rounded-control"
              onClick={() => {
                const raw = norm(quotaDraft).trim()
                onSetQuota(raw === "" ? null : Number(raw))
              }}
            >
              ذخیرهٔ سقف
            </Button>
            <span className="text-micro text-muted-foreground">
              بدون سقف، یک سازمان می‌تواند کل فضای سرور را پر کند.
            </span>
          </div>
        )}
      </section>

      <section className="grid gap-2">
        <h3 className="text-subheading">منبع دانش</h3>
        <p className="mono truncate text-caption text-muted-foreground" dir="ltr">
          {(detail.knowledge_source?.path as string) ?? "پوشه اسناد ثبت نشده است."}
        </p>
        <div className="flex flex-wrap gap-2">
          {Object.keys(counters).length === 0 ? (
            <span className="text-caption text-muted-foreground">سندی ثبت نشده است.</span>
          ) : (
            Object.entries(counters).map(([value, count]) => (
              <span key={value} className="flex items-center gap-1.5">
                <DomainStatus domain="asset" value={value} />
                <span data-numeric className="text-micro text-muted-foreground">
                  {faNum(count)}
                </span>
              </span>
            ))
          )}
        </div>
      </section>

      <section className="grid gap-2">
        <h3 className="flex items-center gap-2 text-subheading">
          <UsersIcon aria-hidden className="size-4 text-muted-foreground" />
          کاربران
          <span data-numeric className="text-micro font-normal text-muted-foreground">
            ({faNum(detail.users.length)})
          </span>
        </h3>
        {detail.users.length === 0 ? (
          <p className="text-caption text-muted-foreground">کاربری ثبت نشده است.</p>
        ) : (
          <ul className="divide-y divide-border rounded-control border border-border">
            {detail.users.map((user) => {
              const isOwner = String(user.id) === String(org.owner_user_id ?? "")
              return (
                <li key={String(user.id)} className="flex items-center gap-3 px-3 py-2">
                  <span className="mono min-w-0 flex-1 truncate text-caption" dir="ltr">
                    {String(user.username)}
                  </span>
                  <span className="text-micro text-muted-foreground">
                    {String(user.membership ?? user.status ?? "")}
                  </span>
                  {isOwner ? (
                    <span className="text-micro font-bold text-primary">مدیر سازمان</span>
                  ) : (
                    onRemoveUser && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        aria-label={"حذف کاربر " + String(user.username)}
                        className="rounded-control text-error hover:bg-error-bg hover:text-error"
                        onClick={() => onRemoveUser(String(user.id), String(user.username))}
                      >
                        حذف
                      </Button>
                    )
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="grid gap-2">
        <h3 className="flex items-center gap-2 text-subheading">
          <FileTextIcon aria-hidden className="size-4 text-muted-foreground" />
          آخرین رویدادها
        </h3>
        {detail.recent_events.length === 0 ? (
          <p className="text-caption text-muted-foreground">رویدادی ثبت نشده است.</p>
        ) : (
          <ul className="divide-y divide-border rounded-control border border-border">
            {detail.recent_events.map((event) => (
              <li key={String(event.id)} className="flex items-center gap-3 px-3 py-2">
                <span className="mono min-w-0 flex-1 truncate text-caption" dir="ltr">
                  {String(event.event)}
                </span>
                <span data-numeric className="text-micro text-muted-foreground">
                  {faDateTime(event.created_at as string)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}