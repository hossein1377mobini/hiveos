import { ActivityIcon, BuildingIcon, CreditCardIcon, TriangleAlertIcon, UsersIcon } from "lucide-react"

import { StatCard } from "../../components/ui/stat-card"
import { DomainStatus } from "../../components/ui/domain-status"
import { Surface } from "../../components/ui/surface"
import { Button } from "../../components/ui/button"
import { faNum } from "../../lib/dates"
import { useLive } from "../useLive"
import { Retry } from "../useLive"

interface LiveStatus {
  health: string
  generated_at?: string
  uptime_seconds: number
  environment?: string
  db: { state: string; migrations_ok?: boolean; latency_ms: number }
  counters: Record<string, number>
  jobs: { open: number; by_status: Record<string, number> }
  process: { pid: number; threads?: number | null }
}

/**
 * Overview workspace.
 *
 * v0.1 opened on the settings tab — a wall of raw JSON was the first thing an
 * administrator saw. The landing view answers "is anything wrong right now?"
 * first and links to the workspace that can fix it. [D3]
 */
export default function OverviewView({ token }: { token: string }) {
  const { data, error, reload } = useLive<LiveStatus>(token, "/system-status", 15_000)

  if (error && !data) return <Retry message={error} onRetry={() => void reload()} />
  if (!data) return <p className="text-caption text-muted-foreground">در حال دریافت وضعیت…</p>

  const counters = data.counters ?? {}
  const attention = data.jobs.open > 0 || data.health !== "green"

  return (
    <div className="grid gap-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="سازمان‌ها"
          value={faNum(counters.organizations ?? 0)}
          hint={faNum(counters.active_organizations ?? 0) + " سازمان فعال"}
          icon={BuildingIcon}
          tone="info"
        />
        <StatCard
          label="کاربران"
          value={faNum(counters.users ?? 0)}
          hint={faNum(counters.active_sessions ?? 0) + " نشست فعال"}
          icon={UsersIcon}
          tone="teal"
        />
        <StatCard
          label="مجموع اعتبار"
          value={faNum(counters.credit_total ?? 0)}
          hint={faNum(counters.wallets ?? 0) + " کیف پول"}
          icon={CreditCardIcon}
          tone="violet"
        />
        <StatCard
          label="کارهای در جریان"
          value={faNum(data.jobs.open ?? 0)}
          hint={faNum(counters.pending_charge_requests ?? 0) + " درخواست شارژ در انتظار"}
          icon={attention ? TriangleAlertIcon : ActivityIcon}
          tone={attention ? "warning" : "success"}
        />
      </div>

      <Surface className="flex flex-wrap items-center justify-between gap-4">
        <div className="grid gap-1">
          <span className="text-micro font-bold text-muted-foreground">سلامت سامانه</span>
          <span className="flex items-center gap-2">
            <DomainStatus domain="health" value={data.health} />
            <span className="text-caption text-muted-foreground">
              پایگاه داده{" "}
              {data.db.state === "up"
                ? "در دسترس (" + faNum(data.db.latency_ms) + " میلی‌ثانیه)"
                : "قطع"}
              {data.db.migrations_ok === false && " — با فایل‌های مایگریشن هم‌خوان نیست"}
            </span>
          </span>
        </div>
        <Button variant="outline" size="sm" className="rounded-control" onClick={() => void reload()}>
          به‌روزرسانی
        </Button>
      </Surface>

      <Surface>
        <h2 className="text-subheading">شمارنده‌ها</h2>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-4">
          {COUNTER_LABELS.map(([key, label]) =>
            counters[key] === undefined ? null : (
              <div key={key}>
                <dt className="text-micro text-muted-foreground">{label}</dt>
                <dd data-numeric className="text-subheading font-bold">
                  {faNum(counters[key])}
                </dd>
              </div>
            ),
          )}
        </dl>
      </Surface>
    </div>
  )
}

const COUNTER_LABELS: Array<[string, string]> = [
  ["organizations", "سازمان‌ها"],
  ["active_organizations", "سازمان‌های فعال"],
  ["users", "کاربران"],
  ["memberships", "عضویت‌های فعال"],
  ["active_sessions", "نشست‌های فعال"],
  ["admin_sessions", "نشست‌های مدیر"],
  ["assets", "اسناد"],
  ["failed_assets", "اسناد ناموفق"],
  ["wallets", "کیف پول‌ها"],
  ["credit_total", "مجموع اعتبار"],
  ["pending_charge_requests", "درخواست شارژ در انتظار"],
  ["executions", "اجراها"],
  ["failed_executions", "اجراهای ناموفق"],
  ["messages", "پیام‌های گفتگو"],
  ["audit_rows", "رکوردهای رویداد"],
]