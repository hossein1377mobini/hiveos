import { useState } from "react"
import { RefreshCwIcon, SaveIcon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "../../components/ui/button"
import { Surface } from "../../components/ui/surface"
import { DomainStatus } from "../../components/ui/domain-status"
import { EmptyState } from "../../components/ui/empty-state"
import { SettingsIcon } from "lucide-react"
import { ErrorText } from "../../components/ui/error-text"
import { faDateTime, faNum } from "../../lib/dates"
import { persianError } from "../../api/errors"
import { adminApi, AdminSessionExpired } from "../api"
import { Retry, useLive } from "../useLive"
import { SETTING_DEFINITIONS, type SettingDefinition } from "../settings-schema"
import {
  SettingsForm,
  toFormValues,
  toPayload,
  type SettingsValues,
} from "../SettingsForm"
import { useCallback, useEffect } from "react"

/**
 * AI workspace.
 *
 * v0.1 exposed five settings as raw JSON textareas. That is the panel's core
 * job — the PO configures providers and models here and nowhere else — so each
 * setting is a described form whose constraints mirror the backend's Pydantic
 * models. Values that the form accepts are values the server accepts. [D8/D13]
 *
 * The live monitoring view (server resources, provider account credit, backup
 * freshness) stays its own panel below the settings.
 */
export default function AiView({ token }: { token: string }) {
  return (
    <div className="grid gap-5">
      <SettingsSection token={token} />
      <MonitoringSection token={token} />
    </div>
  )
}

function SettingsSection({ token }: { token: string }) {
  const [active, setActive] = useState(SETTING_DEFINITIONS[0].key)
  const definition = SETTING_DEFINITIONS.find((d) => d.key === active) ?? SETTING_DEFINITIONS[0]

  return (
    <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
      <nav aria-label="گروه‌های تنظیمات" className="grid content-start gap-1">
        {SETTING_DEFINITIONS.map((entry) => (
          <Button
            key={entry.key}
            variant={entry.key === active ? "secondary" : "ghost"}
            size="sm"
            aria-current={entry.key === active ? "true" : undefined}
            className="h-auto justify-start rounded-control px-3 py-2 text-start text-caption"
            onClick={() => setActive(entry.key)}
          >
            {entry.title}
          </Button>
        ))}
      </nav>
      <SettingPanel key={definition.key} token={token} definition={definition} />
    </div>
  )
}

function SettingPanel({
  token,
  definition,
}: {
  token: string
  definition: SettingDefinition
}) {
  const [values, setValues] = useState<SettingsValues>({})
  const [defaults, setDefaults] = useState<Record<string, string>>({})
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    // A retry after a failure used to render nothing at all: 'loaded' was left
    // true by the finally of the failed attempt, so the spinner branch could
    // never run again and the operator saw a blank panel while the request was
    // in flight.
    setLoaded(false)
    try {
      // GET /settings/{key} answers {key, value}, not the settings object
      // itself. Feeding the wrapper to toFormValues made every field resolve to
      // undefined and render empty - and because PUT replaces the whole stored
      // value, saving that blank form would have overwritten the live provider
      // credentials with defaults.
      // The response carries an extra "default" object for settings whose
      // shipped text lives in the backend (currently the prompt template). It
      // feeds the "restore the suggested text" action, so the operator never
      // has to paste a prompt back in by hand - and never restores a stale
      // copy, because it comes from the same constant the runtime falls back to.
      const stored = await adminApi<{
        key: string
        value: SettingsValues
        default?: Record<string, string>
      }>(token, "GET", "/settings/" + definition.key)
      setValues(toFormValues(definition, stored?.value ?? {}))
      setDefaults(stored?.default ?? {})
      setError(null)
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      setError(err instanceof Error ? err.message : "دریافت تنظیمات ناموفق بود.")
    } finally {
      setLoaded(true)
    }
  }, [token, definition])

  useEffect(() => {
    void load()
  }, [load])

  async function save() {
    const { payload, errors } = toPayload(definition, values)
    if (errors.length > 0) {
      // Show every problem at once: fixing them one 422 at a time is what the
      // raw JSON textarea used to make the operator do.
      toast.error("تنظیمات ذخیره نشد", { description: errors.join(" ") })
      return
    }
    setBusy(true)
    try {
      await adminApi(token, "PUT", "/settings/" + definition.key, { value: payload })
      toast.success("تنظیمات ذخیره شد", { description: definition.title })
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      toast.error(err instanceof Error ? err.message : "ذخیره تنظیمات ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Retry message={error} onRetry={() => void load()} />

  return (
    <Surface className="grid gap-5">
      <div>
        <h2 className="text-heading">{definition.title}</h2>
        <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
          {definition.description}
        </p>
      </div>
      {loaded ? (
        <SettingsForm
          definition={definition}
          values={values}
          onChange={setValues}
          defaults={defaults}
        />
      ) : (
        <p className="text-caption text-muted-foreground">در حال بارگذاری…</p>
      )}
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="outline" className="rounded-control" onClick={() => void load()} disabled={busy}>
          بازگردانی
        </Button>
        <Button className="rounded-control" onClick={() => void save()} disabled={busy || !loaded}>
          <SaveIcon className="size-4" />
          {busy ? "در حال ذخیره…" : "ذخیره"}
        </Button>
      </div>
    </Surface>
  )
}

/* --- Live provider monitoring ---------------------------------------------- */

interface AiSnapshot {
  state: string
  reason?: string
  api_key_masked?: string | null
  configured_models?: Record<string, string>
  credit?: { remaining_irt: number; account_tier: number } | null
  usage?: { transactions: number; tokens_total: number; cost_unit: number } | null
  usage_by_model?: Array<{ model: string; transactions: number; tokens: number }>
  /**
   * One row per active provider package. The backend already sends all of
   * this (ai_monitor._packages); the panel only ever read name and days_left,
   * so an operator could not see what was actually bought, how much of it was
   * left, or which models it covers.
   */
  packages?: Array<{
    name: string | null
    description?: string | null
    remaining_irt: number
    amount_irt?: number
    end_date?: string | null
    days_left: number | null
    models?: string[]
  }>
  covered_models?: string[]
}

interface ModelCheck {
  ok: boolean
  state: string
  model: string | null
  latency_ms?: number
  code?: string
  detail?: string
}

/**
 * "Does the configured model actually answer?" as a button.
 *
 * The provider settings can look complete and still leave every user question
 * failing, because the account has no credit for the configured model. This is
 * the only control that answers the question the operator actually has, so it
 * reports the backend's error code in Persian rather than the developer text.
 */
function ModelCheckButton({ token }: { token: string }) {
  const [check, setCheck] = useState<ModelCheck | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setChecking(true)
    setError(null)
    try {
      setCheck(await adminApi<ModelCheck>(token, "GET", "/monitoring/model-check"))
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      setError(err instanceof Error ? err.message : "آزمایش مدل ناموفق بود.")
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-subheading">آزمایش مدل پاسخ‌دهی</h2>
          <p className="mt-0.5 text-micro text-muted-foreground">
            یک پرسش کوتاه به مدل تنظیم‌شده می‌فرستد تا مطمئن شوید کلید و اعتبار حساب درست کار می‌کند.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="rounded-control"
          disabled={checking}
          data-testid="model-check-button"
          onClick={() => void run()}
        >
          {checking ? "در حال آزمایش…" : "آزمایش مدل پاسخ‌دهی"}
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>
      {check && (
        <div
          role="status"
          data-testid="model-check-result"
          className={
            "rounded-control border px-4 py-3 text-caption " +
            (check.ok
              ? "border-success-border bg-success-bg text-success"
              : "border-error-border bg-error-bg text-error")
          }
        >
          <p className="font-bold">
            {check.ok ? "مدل پاسخ داد و آمادهٔ استفاده است." : "مدل پاسخ نداد."}
          </p>
          <p className="mt-1 text-muted-foreground">
            مدل: <span className="mono">{check.model ?? "—"}</span>
            {check.ok && check.latency_ms !== undefined &&
              " · زمان پاسخ: " + faNum(check.latency_ms) + " میلی‌ثانیه"}
            {!check.ok && check.detail &&
              " · " + persianError(check.code ?? "UNKNOWN", undefined, check.detail)}
          </p>
        </div>
      )}
    </div>
  )
}

function MonitoringSection({ token }: { token: string }) {
  const { data, error, reload } = useLive<AiSnapshot>(token, "/monitoring/ai", 60_000)
  const [refreshing, setRefreshing] = useState(false)

  /**
   * Force a re-read of the provider account.
   *
   * The snapshot above is a 60s poll of a server-side cache, so an operator who
   * has just topped the account up would otherwise stare at a stale balance for
   * a minute with no way to ask again. POST /monitoring/ai/refresh clears that
   * cache; it had no caller at all before this button.
   */
  async function refreshCredit() {
    setRefreshing(true)
    try {
      await adminApi(token, "POST", "/monitoring/ai/refresh")
      await reload()
      toast.success("اعتبار حساب تازه‌سازی شد")
    } catch (err) {
      if (err instanceof AdminSessionExpired) return
      toast.error(err instanceof Error ? err.message : "تازه‌سازی اعتبار ناموفق بود.")
    } finally {
      setRefreshing(false)
    }
  }

  if (error && !data) return <Retry message={error} onRetry={() => void reload()} />
  if (!data) return <p className="text-caption text-muted-foreground">در حال دریافت وضعیت درگاه…</p>

  if (data.state === "unsupported") {
    return (
      <div className="grid gap-4">
        <ModelCheckButton token={token} />
        <EmptyState
          icon={SettingsIcon}
          title="درگاه فعلی امکان گزارش اعتبار را ارائه نمی‌دهد"
          description="این درگاه مصرف را گزارش نمی‌کند، بنابراین باقی‌مانده اعتبار حساب در اینجا نمایش داده نمی‌شود. بردارسازی و رتبه‌بندی روی همین سرور انجام می‌شود و اعتباری مصرف نمی‌کند."
        />
      </div>
    )
  }

  const packages = data.packages ?? []
  // days_left is null when the provider sent an end_date we could not parse;
  // such a package is not "expiring", it is "unknown", and treating null as a
  // small number would raise a false alarm.
  const expiring = packages.filter((pkg) => pkg.days_left !== null && pkg.days_left <= 3)

  return (
    <div className="grid gap-4">
      <ModelCheckButton token={token} />
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-subheading">اعتبار حساب هوش مصنوعی</h2>
        <Button
          variant="outline"
          size="sm"
          className="ms-auto rounded-control"
          onClick={() => void refreshCredit()}
          disabled={refreshing}
          data-testid="ai-credit-refresh"
        >
          <RefreshCwIcon aria-hidden className={refreshing ? "animate-spin" : undefined} />
          {refreshing ? "در حال تازه‌سازی…" : "تازه‌سازی اعتبار"}
        </Button>
      </div>
      {expiring.length > 0 && (
        <Surface data-testid="ai-credit-warning" className="border-warning-border bg-warning-bg">
          {expiring.map((pkg, index) => (
            <p key={(pkg.name ?? "package") + index} className="text-caption">
              {pkg.days_left !== null && pkg.days_left < 1
                ? `بستهٔ «${pkg.name ?? "بی‌نام"}» کمتر از یک روز دیگر به پایان می‌رسد.`
                : `بستهٔ «${pkg.name ?? "بی‌نام"}» تا ${faNum(Math.round(pkg.days_left ?? 0))} روز دیگر به پایان می‌رسد.`}{" "}
              پیش از آن اعتبار تازه تهیه کنید تا پاسخ‌دهی متوقف نشود.
            </p>
          ))}
        </Surface>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Surface>
          <span className="text-micro font-bold text-muted-foreground">باقی‌مانده (تومان)</span>
          <p data-numeric data-testid="ai-balance" className="mt-1 text-title">
            {faNum(Math.round(data.credit?.remaining_irt ?? 0))}
          </p>
        </Surface>
        <Surface>
          <span className="text-micro font-bold text-muted-foreground">مصرف کل توکن</span>
          <p data-numeric className="mt-1 text-title">
            {faNum(data.usage?.tokens_total ?? 0)}
          </p>
        </Surface>
        <Surface>
          <span className="text-micro font-bold text-muted-foreground">تعداد درخواست</span>
          <p data-numeric className="mt-1 text-title">
            {faNum(data.usage?.transactions ?? 0)}
          </p>
        </Surface>
      </div>
      {data.api_key_masked && (
        <p className="mono text-micro text-muted-foreground" dir="ltr">
          API key {data.api_key_masked}
        </p>
      )}
      <PackagesPanel packages={packages} />

      <div className="flex flex-wrap gap-2">
        {Object.entries(data.configured_models ?? {}).map(([role, model]) => (
          <span key={role} className="flex items-center gap-1.5">
            <DomainStatus domain="health" value="ok" />
            <span className="mono text-micro" dir="ltr">
              {role}: {model}
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}

/**
 * The active packages, itemised.
 *
 * The account total alone is not actionable: AvalAI scopes credit per package
 * and per model allowlist, so an operator looking at "۱٬۳۴۴٬۰۱۳ تومان باقی
 * مانده" still cannot tell whether the model they configured is covered, nor
 * which package is about to lapse. Each row therefore carries the remaining
 * amount against what was bought, the expiry in both Jalali and "in N days",
 * and the models that package still covers.
 */
function PackagesPanel({ packages }: { packages: NonNullable<AiSnapshot["packages"]> }) {
  if (packages.length === 0) {
    return (
      <Surface data-testid="ai-packages-empty">
        <h2 className="text-subheading">بسته‌های فعال</h2>
        <p className="mt-1 text-caption text-muted-foreground">
          درگاه هیچ بستهٔ فعالی برای این حساب گزارش نکرد. اگر تازه اعتبار خریده‌اید،
          «تازه‌سازی اعتبار» را بزنید.
        </p>
      </Surface>
    )
  }

  return (
    <Surface data-testid="ai-packages">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-subheading">بسته‌های فعال</h2>
        <span className="text-micro text-muted-foreground">
          {faNum(packages.length)} بسته
        </span>
      </div>
      <div className="mt-3 grid gap-3">
        {packages.map((pkg, index) => {
          const days = pkg.days_left
          // Three bands rather than two: a package can be paid-up but nearly
          // over, and that is the case worth flagging before it stops answering.
          const tone =
            days === null
              ? "border-border"
              : days <= 1
                ? "border-error-border bg-error-bg"
                : days <= 3
                  ? "border-warning-border bg-warning-bg"
                  : "border-border"
          return (
            <div
              key={(pkg.name ?? "package") + index}
              className={"rounded-control border px-4 py-3 " + tone}
              data-testid="ai-package-row"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-caption font-bold">{pkg.name ?? "بستهٔ بی‌نام"}</span>
                {days !== null && (
                  <span
                    className={
                      "rounded-pill px-2 py-0.5 text-micro font-bold " +
                      (days <= 1
                        ? "bg-error text-white"
                        : days <= 3
                          ? "bg-warning text-white"
                          : "bg-secondary text-muted-foreground")
                    }
                    data-testid="ai-package-days"
                  >
                    {days < 1
                      ? "کمتر از یک روز مانده"
                      : faNum(Math.round(days)) + " روز مانده"}
                  </span>
                )}
              </div>
              {pkg.description && (
                <p className="mt-1 text-micro text-muted-foreground">{pkg.description}</p>
              )}
              <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                <div>
                  <dt className="text-micro text-muted-foreground">باقی‌ماندهٔ بسته</dt>
                  <dd data-numeric className="text-caption font-bold">
                    {faNum(Math.round(pkg.remaining_irt ?? 0))} تومان
                  </dd>
                </div>
                {pkg.amount_irt !== undefined && pkg.amount_irt !== null && (
                  <div>
                    <dt className="text-micro text-muted-foreground">مبلغ خرید</dt>
                    <dd data-numeric className="text-caption">
                      {faNum(Math.round(pkg.amount_irt))} تومان
                    </dd>
                  </div>
                )}
                {pkg.end_date && (
                  <div>
                    <dt className="text-micro text-muted-foreground">تاریخ پایان</dt>
                    <dd className="text-caption">{faDateTime(pkg.end_date)}</dd>
                  </div>
                )}
              </dl>
              {(pkg.models ?? []).length > 0 && (
                <details className="mt-2.5">
                  <summary className="cursor-pointer text-micro font-bold text-muted-foreground">
                    مدل‌های تحت پوشش ({faNum((pkg.models ?? []).length)})
                  </summary>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(pkg.models ?? []).map((model) => (
                      <span
                        key={model}
                        className="mono rounded-pill border border-border bg-secondary px-2 py-0.5 text-micro"
                        dir="ltr"
                      >
                        {model}
                      </span>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )
        })}
      </div>
    </Surface>
  )
}