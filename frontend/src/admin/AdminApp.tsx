import { useCallback, useEffect, useRef, useState } from "react";
import { MonitoringTab } from "./MonitoringTab";
import { persianError } from "../api/errors";
import { Field } from "../components/auth/parts";
import { Input } from "../components/ui/input";
import { Surface } from "../components/ui/surface";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

// Admin panel UI (epic-16, zero-open): the System Admin logs in and sets
// provider credentials, allowlist, pricing, pipeline and the prompt template;
// manages organizations + manual credit and approves wallet charge requests.
// Values stay EMPTY by default — the PO fills them here (his explicit role).
const ADMIN_BASE = "/api/v1/admin";

interface Envelope {
  success: boolean;
  data?: unknown;
  error?: { code: string; message: string };
}

/** Thrown when the admin session is gone, so the shell can log out. */
export class AdminSessionExpired extends Error {}

// The tabs each call adminApi from their own catch blocks; a dead session must
// log the whole panel out regardless of which tab noticed it.
let sessionExpiredHandler: (() => void) | null = null;

export function setAdminSessionExpiredHandler(handler: (() => void) | null): void {
  sessionExpiredHandler = handler;
}

export async function adminApi<T>(
  token: string,
  method: "GET" | "PUT" | "POST" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(ADMIN_BASE + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  // F: an expired/revoked admin token answers 403 (and a proxy 502+ answers
  // HTML) - both used to surface as "Unexpected token" or a silently dead tab.
  let payload: Envelope | null = null;
  try {
    payload = (await response.json()) as Envelope;
  } catch {
    payload = null;
  }
  if (response.status === 403 && payload?.error?.code === "ADMIN_FORBIDDEN") {
    sessionExpiredHandler?.();
    throw new AdminSessionExpired("نشست مدیر منقضی شده است.");
  }
  if (payload === null) {
    throw new Error(persianError("CLIENT_BAD_RESPONSE", response.status));
  }
  if (!payload.success || payload.data === undefined) {
    // PO request: the panel never shows the server's English developer text.
    throw new Error(
      persianError(payload.error?.code ?? "UNKNOWN", response.status, payload.error?.message),
    );
  }
  return payload.data as T;
}

type Tab = "monitoring" | "settings" | "orgs" | "requests" | "logs" | "status";

const SETTING_KEYS = [
  { key: "providers_pricing", title: "درگاه مدل و قیمت", hint: "provider: mock | online-mock | openai-compatible" },
  { key: "models_allowlist", title: "لیست مدل‌های مجاز", hint: "مثال: {\"models\": [\"gpt-x\"], \"default\": \"gpt-x\"}" },
  { key: "pipeline", title: "پایپ‌لاین بازیابی", hint: "تنظیمات مرحلهٔ بازیابی دانش" },
  { key: "prompt_template", title: "قالب پرامپت", hint: "system + user_template با {question} و {context}" },
] as const;

/** Shared retry affordance: a failed panel view offers «تلاش مجدد». */
export function Retry({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      data-testid="admin-retry"
      className="flex flex-wrap items-center gap-3 rounded-control border border-error bg-error-bg px-3 py-2.5"
    >
      <p className="text-[13px] font-bold text-error">{message}</p>
      <button
        type="button"
        className="rounded-control border px-3 py-1 text-xs font-bold bg-primary text-primary-foreground hover:bg-primary/90"
        onClick={onRetry}
      >
        تلاش مجدد
      </button>
    </div>
  );
}

/**
 * The panel polls the live status while the tab is open: the PO asked for the
 * server state "at a glance", not for a snapshot from page-load time.
 */
function useLive<T>(token: string, path: string, everyMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await adminApi<T>(token, "GET", path);
      setData(next);
      setError(null);
      setUpdatedAt(new Date());
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      if (data === null) setError(err instanceof Error ? err.message : "دریافت اطلاعات ناموفق بود.");
    } finally {
      setLoading(false);
    }
    // 'data' is only read as a "have we ever loaded?" flag, so it must not
    // restart the polling effect on every tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, path]);

  useEffect(() => {
    void load();
    timer.current = setInterval(() => void load(), everyMs);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load, everyMs]);

  return { data, error, loading, updatedAt, reload: load };
}

export default function AdminApp() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem("hiveos.admin"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("settings");

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const response = await fetch(ADMIN_BASE + "/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      let payload: Envelope | null = null;
      try {
        payload = (await response.json()) as Envelope;
      } catch {
        payload = null;
      }
      const data = payload?.data as { token?: string } | undefined;
      if (payload === null || !payload.success || !data?.token) {
        throw new Error(
          persianError(
            payload?.error?.code ?? "CLIENT_BAD_RESPONSE",
            response.status,
            payload?.error?.message,
          ),
        );
      }
      sessionStorage.setItem("hiveos.admin", data.token);
      setToken(data.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ورود ناموفق بود.");
    }
  }

  function logout() {
    sessionStorage.removeItem("hiveos.admin");
    setToken(null);
  }

  useEffect(() => {
    setAdminSessionExpiredHandler(() => {
      logout();
      setError("نشست مدیر منقضی شده است؛ دوباره وارد شوید.");
    });
    return () => setAdminSessionExpiredHandler(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!token) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <form
          onSubmit={login}
          className="w-full max-w-sm rounded-card border border-border bg-card p-6 shadow-card"
          aria-label="ورود مدیر سامانه"
        >
          <h1 className="text-lg font-bold">پنل مدیریت HiveOS</h1>
          <Field label="نام کاربری" htmlFor="admin-username" className="mb-0 mt-4">
            <Input
              id="admin-username"
              className="rounded-control text-sm"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              dir="ltr"
              required
            />
          </Field>
          <Field label="گذرواژه" htmlFor="admin-password" className="mb-0 mt-3">
            <Input
              id="admin-password"
              type="password"
              className="rounded-control text-sm"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              dir="ltr"
              required
            />
          </Field>
          {error && (
            <p role="alert" className="mt-3 text-sm text-error" data-testid="admin-error">
              {error}
            </p>
          )}
          <button className="mt-4 w-full rounded-control px-4 py-2 text-sm font-bold bg-primary text-primary-foreground hover:bg-primary/90">
            ورود
          </button>
        </form>
      </main>
    );
  }

  const tabs: ReadonlyArray<{ id: Tab; label: string }> = [
    { id: "monitoring", label: "پایش سرور و هوش مصنوعی" },
    { id: "status", label: "وضعیت سامانه" },
    { id: "logs", label: "رویدادها" },
    { id: "orgs", label: "سازمان‌ها" },
    { id: "requests", label: "درخواست‌های شارژ" },
    { id: "settings", label: "تنظیمات" },
  ];

  return (
    <div className="min-h-dvh bg-secondary">
      <header className="border-b border-border bg-card px-4 py-2">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <h1 className="text-base font-bold">پنل مدیریت HiveOS</h1>
          <button type="button" className="text-sm bg-primary text-primary-foreground hover:bg-primary/90" onClick={logout}>
            خروج
          </button>
        </div>
      </header>
      <nav className="mx-auto mt-4 flex max-w-5xl flex-wrap gap-2 px-4" aria-label="بخش‌های پنل">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
            className={
              "rounded-control px-3 py-2 text-sm " +
              (tab === t.id ? "bg-primary font-bold text-primary-foreground" : "bg-card text-muted-foreground")
            }
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="mx-auto max-w-5xl px-4 py-4">
        {tab === "monitoring" && <MonitoringTab token={token} />}
        {tab === "settings" && <SettingsTab token={token} />}
        {tab === "orgs" && <OrgsTab token={token} />}
        {tab === "requests" && <RequestsTab token={token} />}
        {tab === "logs" && <LogsTab token={token} />}
        {tab === "status" && <StatusTab token={token} />}
      </main>
    </div>
  );
}

function SettingsTab({ token }: { token: string }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded: Record<string, string> = {};
    for (const { key } of SETTING_KEYS) {
      try {
        const data = await adminApi<Record<string, unknown>>(token, "GET", "/settings/" + key);
        loaded[key] = JSON.stringify(data, null, 2);
      } catch (err) {
        if (err instanceof AdminSessionExpired) return;
        loaded[key] = "";
        setError(err instanceof Error ? err.message : "دریافت تنظیمات ناموفق بود.");
      }
    }
    setValues(loaded);
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(key: string, text: string) {
    setError(null);
    setSaved(null);
    let parsed: unknown;
    try {
      parsed = text.trim() ? JSON.parse(text) : {};
    } catch {
      setError("ساختار JSON واردشده معتبر نیست؛ آن را اصلاح کنید.");
      return;
    }
    try {
      await adminApi(token, "PUT", "/settings/" + key, { value: parsed });
      setSaved(key);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setError(err instanceof Error ? err.message : "ذخیره تنظیمات ناموفق بود.");
    }
  }

  return (
    <div className="space-y-4">
      {SETTING_KEYS.map(({ key, title, hint }) => (
        <Surface key={key} className="p-4">
          <h2 className="text-sm font-bold">{title}</h2>
          <p className="mt-1 text-xs text-muted-foreground" dir="auto">
            {hint}
          </p>
          <textarea
            dir="ltr"
            rows={5}
            className="mt-2 w-full rounded-control border p-2 font-mono text-xs border-border bg-card"
            aria-label={title}
            value={values[key] ?? ""}
            onChange={(e) => setValues({ ...values, [key]: e.target.value })}
          />
          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              className="rounded-control px-4 py-2 text-sm font-bold bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={() => save(key, values[key] ?? "")}
            >
              ذخیره
            </button>
            {saved === key && <span className="text-sm text-success">ذخیره شد ✓</span>}
          </div>
        </Surface>
      ))}
      {error && (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      )}
    </div>
  );
}

interface Org {
  id: string;
  name: string;
  status: string;
  balance: number;
  plan?: string;
  plan_expires_at?: string | null;
  industry?: string | null;
  size?: string | null;
  created_at?: string;
  users?: number;
  assets?: number;
  chat_sessions?: number;
  executions?: number;
  last_activity_at?: string | null;
}

interface OrgDetail {
  organization: Record<string, unknown>;
  users: Array<Record<string, unknown>>;
  wallet_transactions: Array<Record<string, unknown>>;
  charge_requests: ChargeRequestItem[];
  recent_events: Array<Record<string, unknown>>;
  assets_by_status: Record<string, number>;
  knowledge_source: Record<string, unknown> | null;
}

const STATUS_FA: Record<string, string> = {
  pending: "در انتظار تأیید",
  active: "فعال",
  suspended: "معلق",
  disabled: "غیرفعال",
  expired: "منقضی",
};

const faNum = (value: number): string => value.toLocaleString("fa-IR");

const sizeText = (value: unknown): string => {
  const size = Number(value ?? 0);
  if (!Number.isFinite(size) || size <= 0) return "صفر";
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"];
  let scaled = size;
  let unit = 0;
  while (scaled >= 1024 && unit < units.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  return faNum(Math.round(scaled * 10) / 10) + " " + units[unit];
};

const faDate = (value: unknown): string => {
  if (typeof value !== "string" || !value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toISOString().slice(0, 10);
};

function OrgsTab({ token }: { token: string }) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [amounts, setAmounts] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<OrgDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [quotaSaved, setQuotaSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await adminApi<{ organizations: Org[] }>(token, "GET", "/organizations");
      setOrgs(data.organizations ?? []);
      setError(null);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setError(err instanceof Error ? err.message : "دریافت فهرست سازمان‌ها ناموفق بود.");
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = useCallback(
    async (id: string) => {
      setOpenId(id);
      setDetail(null);
      setDetailError(null);
      try {
        setDetail(await adminApi<OrgDetail>(token, "GET", "/organizations/" + id));
      } catch (err) {
        if (err instanceof AdminSessionExpired) return;
        setDetailError(err instanceof Error ? err.message : "دریافت جزئیات سازمان ناموفق بود.");
      }
    },
    [token],
  );

  // FR-011: the storage cap is what stops one tenant filling the shared
  // volume. Saved per organization, and the detail view reloads so the PO
  // sees the new figure rather than the one they typed.
  async function setQuota(orgId: string, value: number | null) {
    setBusy(orgId);
    setNotice(null);
    setQuotaSaved(false);
    try {
      await adminApi(token, "PUT", "/organizations/" + orgId + "/storage-quota", {
        storage_quota_mb: value,
      });
      setQuotaSaved(true);
      await openDetail(orgId);
      window.setTimeout(() => setQuotaSaved(false), 2500);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setNotice(err instanceof Error ? err.message : "ذخیرهٔ سقف فضا ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  // PO request: every action that changes money or access states what it does
  // and asks for confirmation first (credit = irreversible for the operator).
  async function credit(orgId: string, name: string) {
    const amount = amounts[orgId] ?? 0;
    if (!Number.isFinite(amount) || amount === 0) {
      setNotice("مبلغ اعتبار را وارد کنید.");
      return;
    }
    if (!window.confirm(`افزودن ${amount} اعتبار به «${name}»؟ این کار دفتر کل کیف پول را تغییر می‌دهد.`)) {
      return;
    }
    setBusy(orgId);
    setNotice(null);
    try {
      await adminApi(token, "POST", "/organizations/" + orgId + "/credit", { amount });
      setNotice(`اعتبار افزوده شد ✓ (${name})`);
      await load();
      if (openId === orgId) await openDetail(orgId);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setNotice(err instanceof Error ? err.message : "افزودن اعتبار ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  // PO request: an admin must be able to wipe a registration so the same owner
  // can sign up again. Deleting is irreversible AND removes the owner account,
  // so the confirmation spells out exactly what disappears.
  async function removeOrg(orgId: string, name: string, users: number) {
    const typed = window.prompt(
      `حذف کامل سازمان «${name}»؟\n\n` +
        `با این کار همهٔ اسناد، گفتگوها، کیف پول و ${users} کاربرِ این سازمان حذف می‌شود و ` +
        `همین کاربر می‌تواند دوباره ثبت‌نام کند. این کار برگشت‌پذیر نیست.\n\n` +
        `برای تأیید، نام سازمان را دقیقاً بنویسید:`,
      "",
    );
    if (typed === null) return;
    if (typed.trim() !== name) {
      setNotice("نام سازمان مطابق نبود؛ حذف انجام نشد.");
      return;
    }
    setBusy(orgId);
    setNotice(null);
    try {
      const result = await adminApi<{ removed_users: number }>(
        token,
        "DELETE",
        "/organizations/" + orgId,
      );
      setNotice(
        `سازمان «${name}» حذف شد و ${result.removed_users ?? 0} کاربر آن آزاد شد؛ ثبت‌نام دوباره ممکن است.`,
      );
      setOpenId(null);
      setDetail(null);
      await load();
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setNotice(err instanceof Error ? err.message : "حذف سازمان ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  async function removeUser(orgId: string, userId: string, username: string) {
    if (!window.confirm(`کاربر «${username}» از این سازمان حذف شود؟`)) return;
    setBusy(orgId);
    setNotice(null);
    try {
      const result = await adminApi<{ account_removed: boolean }>(
        token,
        "DELETE",
        "/organizations/" + orgId + "/users/" + userId,
      );
      setNotice(
        result.account_removed
          ? `کاربر «${username}» و حسابش حذف شد.`
          : `کاربر «${username}» از این سازمان حذف شد (حسابش در سازمان دیگری باقی است).`,
      );
      await load();
      if (openId === orgId) await openDetail(orgId);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setNotice(err instanceof Error ? err.message : "حذف کاربر ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <Retry message={error} onRetry={() => void load()} />;

  return (
    <div className="space-y-4">
      {notice && <p className="text-sm text-success">{notice}</p>}
      <Surface className="overflow-hidden p-0">
        <Table>
        <TableHeader>
          <TableRow className="border-border text-muted-foreground">
            <TableHead className="p-3">سازمان</TableHead>
            <TableHead className="p-3">وضعیت</TableHead>
            <TableHead className="p-3">موجودی</TableHead>
            <TableHead className="p-3">کاربران / اسناد</TableHead>
            <TableHead className="p-3">پلن</TableHead>
            <TableHead className="p-3">افزودن اعتبار</TableHead>
            <TableHead className="p-3">حذف</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orgs.map((o) => (
            <TableRow key={o.id} className="border-border align-top">
              <TableCell className="p-3">
                <button
                  type="button"
                  className="font-bold text-primary underline bg-primary text-primary-foreground hover:bg-primary/90"
                  onClick={() => (openId === o.id ? setOpenId(null) : void openDetail(o.id))}
                >
                  {o.name}
                </button>
                <span className="block text-[11px] text-muted-foreground" dir="ltr">
                  {faDate(o.created_at)}
                </span>
              </TableCell>
              <TableCell className="p-3">{STATUS_FA[o.status] ?? o.status}</TableCell>
              <TableCell className="p-3" data-testid={"balance-" + o.id}>
                {o.balance}
              </TableCell>
              <TableCell className="p-3 text-xs">
                {o.users ?? 0} / {o.assets ?? 0}
              </TableCell>
              <TableCell className="p-3 text-xs">
                {o.plan ?? "trial"}
                {o.plan_expires_at && (
                  <span dir="ltr" className="block text-muted-foreground">
                    {faDate(o.plan_expires_at)}
                  </span>
                )}
              </TableCell>
              <TableCell className="p-3">
                <div className="flex gap-2">
                  <input
                    type="number"
                    aria-label={"مبلغ برای " + o.name}
                    className="w-24 rounded-control border px-2 py-1 border-border bg-card"
                    value={amounts[o.id] ?? ""}
                    onChange={(e) => setAmounts({ ...amounts, [o.id]: Number(e.target.value) })}
                  />
                  <button
                    type="button"
                    disabled={busy === o.id}
                    className="rounded-control px-3 py-1 font-bold disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90"
                    onClick={() => void credit(o.id, o.name)}
                  >
                    اعمال
                  </button>
                </div>
              </TableCell>
              <TableCell className="p-3">
                <button
                  type="button"
                  disabled={busy === o.id}
                  aria-label={"حذف سازمان " + o.name}
                  className="rounded-control border border-error px-3 py-1 font-bold text-error disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90"
                  onClick={() => void removeOrg(o.id, o.name, o.users ?? 0)}
                >
                  حذف سازمان
                </button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        </Table>
      </Surface>
      {orgs.length === 0 && <p className="text-sm text-muted-foreground">سازمانی ثبت نشده است.</p>}

      {openId && (
        <Surface className="p-4" aria-label="جزئیات سازمان">
          <h2 className="text-sm font-bold">جزئیات سازمان</h2>
          {detailError && <Retry message={detailError} onRetry={() => void openDetail(openId)} />}
          {!detail && !detailError && <p className="mt-2 text-sm text-muted-foreground">در حال بارگذاری…</p>}
          {detail && (
            <OrgDetailView
              detail={detail}
              busy={busy === String(detail.organization.id)}
              quotaSaved={quotaSaved}
              onSetQuota={(value) => void setQuota(String(detail.organization.id), value)}
              onRemoveUser={(userId, username) =>
                void removeUser(String(detail.organization.id), userId, username)
              }
            />
          )}
        </Surface>
      )}
    </div>
  );
}

export function OrgDetailView({
  detail,
  busy,
  onRemoveUser,
  onSetQuota,
  quotaSaved,
}: {
  detail: OrgDetail;
  busy?: boolean;
  onRemoveUser?: (userId: string, username: string) => void;
  onSetQuota?: (value: number | null) => void;
  quotaSaved?: boolean;
}) {
  const org = detail.organization;
  const counters = detail.assets_by_status ?? {};
  const [quotaDraft, setQuotaDraft] = useState(
    org.storage_quota_mb === null || org.storage_quota_mb === undefined
      ? ""
      : String(org.storage_quota_mb),
  );
  return (
    <div className="mt-3 space-y-4 text-sm">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4">
        {([
          ["صنعت", org.industry ?? "—"],
          ["اندازه", org.size ?? "—"],
          ["مدیر", org.owner_username ?? "—"],
          ["موجودی", org.balance ?? 0],
          ["پلن", org.plan ?? "—"],
          ["انقضای پلن", faDate(org.plan_expires_at)],
          [
            "فضای مصرفی",
            sizeText(org.storage_bytes) +
              (org.storage_quota_mb ? " از " + faNum(Number(org.storage_quota_mb)) + " مگابایت" : " (بی‌سقف)"),
          ],
          ["ساخت", faDate(org.created_at)],
          ["آخرین فعالیت", faDate(org.last_activity_at)],
        ] as Array<[string, React.ReactNode]>).map(([label, value]) => (
          <div key={String(label)}>
            <dt className="text-[11px] text-muted-foreground">{label}</dt>
            <dd className="font-bold">{String(value)}</dd>
          </div>
        ))}
      </dl>

      <div>
        <h3 className="text-xs font-bold text-muted-foreground">وضعیت اسناد</h3>
        <p className="mt-1 text-xs">
          {Object.keys(counters).length === 0
            ? "سندی ثبت نشده است."
            : Object.entries(counters)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ")}
        </p>
        <p className="mt-1 text-xs" dir="ltr">
          {(detail.knowledge_source?.path as string) ?? "پوشه اسناد ثبت نشده است."}
        </p>
      </div>

      {onSetQuota && (
        <div>
          <h3 className="text-xs font-bold text-muted-foreground">سقف فضای ذخیره‌سازی</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">
            بدون سقف، یک سازمان می‌تواند کل فضای سرور را پر کند و بقیه را از کار بیندازد.
            خالی گذاشتن یعنی بی‌سقف.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Input
              type="number"
              min={1}
              className="w-32"
              aria-label="سقف فضای ذخیره‌سازی به مگابایت"
              value={quotaDraft}
              placeholder="بی‌سقف"
              onChange={(e) => setQuotaDraft(e.target.value)}
            />
            <span className="text-xs text-muted-foreground">مگابایت</span>
            <button
              type="button"
              disabled={busy}
              data-testid="save-quota"
              onClick={() => {
                const raw = quotaDraft.trim();
                onSetQuota(raw === "" ? null : Number(raw));
              }}
              className="rounded-control border px-3 py-1.5 text-xs font-bold hover:bg-muted disabled:opacity-50"
            >
              ذخیرهٔ سقف
            </button>
            {quotaSaved && <span className="text-xs font-bold text-success">ذخیره شد</span>}
          </div>
        </div>
      )}

      <div>
        <h3 className="text-xs font-bold text-muted-foreground">کاربران ({detail.users.length})</h3>
        <ul className="mt-1 space-y-1 text-xs">
          {detail.users.map((u) => (
            <li key={String(u.id)} className="flex justify-between border-b border-border py-1">
              <span dir="ltr">{String(u.username)}</span>
              <span className="flex items-center gap-3">
                <span className="text-muted-foreground">{String(u.membership ?? u.status)}</span>
                {onRemoveUser &&
                  String(u.id) !== String(detail.organization.owner_user_id ?? "") && (
                    <button
                      type="button"
                      disabled={busy}
                      aria-label={"حذف کاربر " + String(u.username)}
                      className="text-error underline disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90"
                      onClick={() => onRemoveUser(String(u.id), String(u.username))}
                    >
                      حذف
                    </button>
                  )}
              </span>
            </li>
          ))}
          {detail.users.length === 0 && <li className="text-muted-foreground">کاربری ثبت نشده است.</li>}
        </ul>
      </div>

      <div>
        <h3 className="text-xs font-bold text-muted-foreground">آخرین رویدادها</h3>
        <ul className="mt-1 space-y-1 text-xs">
          {detail.recent_events.map((e) => (
            <li key={String(e.id)} className="flex justify-between border-b border-border py-1">
              <span dir="ltr">{String(e.event)}</span>
              <span className="text-muted-foreground" dir="ltr">
                {faDate(e.created_at)}
              </span>
            </li>
          ))}
          {detail.recent_events.length === 0 && <li className="text-muted-foreground">رویدادی ثبت نشده است.</li>}
        </ul>
      </div>
    </div>
  );
}

interface ChargeRequestItem {
  id: string;
  organization_id: string;
  amount: number;
  status: string;
  note: string | null;
}

function RequestsTab({ token }: { token: string }) {
  const [items, setItems] = useState<ChargeRequestItem[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await adminApi<{ requests: ChargeRequestItem[] }>(token, "GET", "/charge-requests");
      setItems(data.requests ?? []);
      setError(null);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setError(err instanceof Error ? err.message : "دریافت درخواست‌ها ناموفق بود.");
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(id: string, approve: boolean) {
    setError(null);
    try {
      await adminApi(token, "POST", "/charge-requests/" + id + "/decision", { approve });
      await load();
      setMsg(approve ? "تأیید شد و اعتبار افزوده شد ✓" : "رد شد ✓");
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setError(err instanceof Error ? err.message : "ثبت تصمیم ناموفق بود.");
    }
  }

  if (error && items.length === 0) return <Retry message={error} onRetry={() => void load()} />;

  return (
    <div className="space-y-3">
      {msg && <p className="text-sm text-success">{msg}</p>}
      {error && <p className="text-sm text-error">{error}</p>}
      {items.length === 0 && <p className="text-sm text-muted-foreground">درخواستی ثبت نشده است.</p>}
      {items.map((r) => (
        <Surface
          key={r.id}
          className="flex items-center justify-between p-4"
        >
          <div className="text-sm">
            <p className="font-bold" dir="ltr">
              {r.amount} — {r.status}
            </p>
            {r.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
          </div>
          {r.status === "PENDING" && (
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-control bg-success px-3 py-1 text-sm font-bold bg-primary text-primary-foreground hover:bg-primary/90"
                onClick={() => void decide(r.id, true)}
              >
                تأیید
              </button>
              <button
                type="button"
                className="rounded-control bg-error px-3 py-1 text-sm font-bold bg-primary text-primary-foreground hover:bg-primary/90"
                onClick={() => void decide(r.id, false)}
              >
                رد
              </button>
            </div>
          )}
        </Surface>
      ))}
    </div>
  );
}

interface LogRow {
  id: string;
  event: string;
  level: string;
  entity_type: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
  organization_name: string | null;
  actor_username: string | null;
}

interface LogsPayload {
  total: number;
  limit: number;
  offset: number;
  logs: LogRow[];
  server_log: { path: string | null; available: boolean; lines: string[] };
}

const LEVELS = [
  { id: "all", label: "همه" },
  { id: "activity", label: "فعالیت‌ها" },
  { id: "error", label: "خطاها" },
] as const;

function LogsTab({ token }: { token: string }) {
  const [level, setLevel] = useState<(typeof LEVELS)[number]["id"]>("all");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [payload, setPayload] = useState<LogsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const limit = 50;

  const load = useCallback(async () => {
    try {
      const data = await adminApi<LogsPayload>(
        token,
        "GET",
        `/logs?level=${level}&limit=${limit}&offset=${offset}` +
          (q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ""),
      );
      setPayload(data);
      setError(null);
    } catch (err) {
      if (err instanceof AdminSessionExpired) return;
      setError(err instanceof Error ? err.message : "دریافت رویدادها ناموفق بود.");
    }
  }, [token, level, offset, q]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !payload) return <Retry message={error} onRetry={() => void load()} />;

  const total = payload?.total ?? 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {LEVELS.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => {
              setLevel(l.id);
              setOffset(0);
            }}
            aria-current={level === l.id ? "page" : undefined}
            className={
              "rounded-control px-3 py-1.5 text-xs " +
              (level === l.id ? "bg-primary font-bold text-primary-foreground" : "bg-card text-muted-foreground")
            }
          >
            {l.label}
          </button>
        ))}
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
          placeholder="جستجو در رویداد، سازمان یا کاربر…"
          aria-label="جستجوی رویداد"
          className="ms-auto w-64 rounded-control border px-3 py-1.5 text-xs border-border bg-card"
        />
      </div>

      {error && <p className="text-sm text-error">{error}</p>}
      <Surface className="overflow-hidden p-0">
        <Table>
        <TableHeader>
          <TableRow className="border-border text-muted-foreground">
            <TableHead className="p-2">زمان</TableHead>
            <TableHead className="p-2">رویداد</TableHead>
            <TableHead className="p-2">سازمان</TableHead>
            <TableHead className="p-2">کاربر</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(payload?.logs ?? []).map((row) => (
            <TableRow key={row.id} className="border-border">
              <TableCell className="p-2 whitespace-nowrap" dir="ltr">
                {row.created_at ? new Date(row.created_at).toISOString().replace("T", " ").slice(0, 19) : "—"}
              </TableCell>
              <TableCell className="p-2" dir="ltr">
                <span className={row.level === "error" ? "font-bold text-error" : ""}>{row.event}</span>
                {row.detail && (
                  <span className="block text-[10.5px] text-muted-foreground">
                    {JSON.stringify(row.detail)}
                  </span>
                )}
              </TableCell>
              <TableCell className="p-2">{row.organization_name ?? "—"}</TableCell>
              <TableCell className="p-2" dir="ltr">
                {row.actor_username ?? "سامانه"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        </Table>
      </Surface>
      {total === 0 && <p className="text-sm text-muted-foreground">رویدادی با این فیلتر ثبت نشده است.</p>}

      {total > limit && (
        <div className="flex items-center gap-3 text-xs">
          <button
            type="button"
            disabled={offset === 0}
            className="rounded-control border px-3 py-1 disabled:opacity-40 bg-primary text-primary-foreground hover:bg-primary/90"
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            صفحهٔ قبل
          </button>
          <span>
            {offset + 1}–{Math.min(offset + limit, total)} از {total}
          </span>
          <button
            type="button"
            disabled={offset + limit >= total}
            className="rounded-control border px-3 py-1 disabled:opacity-40 bg-primary text-primary-foreground hover:bg-primary/90"
            onClick={() => setOffset(offset + limit)}
          >
            صفحهٔ بعد
          </button>
        </div>
      )}

      {payload?.server_log?.available && (
        <details className="rounded-card border border-border bg-card p-3">
          <summary className="cursor-pointer text-xs font-bold">گزارش فایل سرور</summary>
          <pre dir="ltr" className="mt-2 max-h-72 overflow-auto text-[10.5px] leading-relaxed">
            {payload.server_log.lines.slice(-200).join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}

interface LiveStatus {
  health: string;
  generated_at?: string;
  uptime_seconds: number;
  environment?: string;
  db: {
    state: string;
    migration_head: string | null;
    expected_head?: string | null;
    migrations_ok?: boolean;
    latency_ms: number;
    size_bytes?: number | null;
    connections?: number | null;
  };
  counters: Record<string, number>;
  last_audit_at?: string | null;
  jobs: { open: number; by_status: Record<string, number> };
  process: { pid: number; started_at?: string; threads?: number | null };
  host: {
    load: { "1m": number | null; "5m": number | null; "15m": number | null };
    disk: { root: string | null; total_bytes: number | null; free_bytes: number | null; uploads_bytes: number | null };
  };
  llm_provider: string;
  sms_provider: string;
  embedding_provider: string;
  services: Record<string, string>;
}

const COUNTER_FA: Record<string, string> = {
  organizations: "سازمان‌ها",
  active_organizations: "سازمان‌های فعال",
  users: "کاربران",
  memberships: "عضویت‌های فعال",
  active_sessions: "نشست‌های فعال",
  admin_sessions: "نشست‌های مدیر",
  assets: "اسناد",
  failed_assets: "اسناد ناموفق",
  wallets: "کیف پول‌ها",
  credit_total: "مجموع اعتبار",
  pending_charge_requests: "درخواست شارژ در انتظار",
  executions: "اجراها",
  failed_executions: "اجراهای ناموفق",
  messages: "پیام‌های گفتگو",
  audit_rows: "رکوردهای رویداد",
};

const HEALTH_FA: Record<string, { label: string; tone: string }> = {
  green: { label: "سالم", tone: "text-success" },
  degraded: { label: "نیازمند بررسی", tone: "text-warning" },
  red: { label: "اختلال", tone: "text-error" },
};

const bytes = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(1)} ${units[i]}`;
};

const duration = (seconds: number): string => {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d} روز و ${h} ساعت`;
  if (h > 0) return `${h} ساعت و ${m} دقیقه`;
  return `${m} دقیقه`;
};

function StatusTab({ token }: { token: string }) {
  // PO request: live values, refreshed every 10s while the tab stays open.
  const { data, error, updatedAt, reload } = useLive<LiveStatus>(token, "/system-status", 10_000);

  if (error && !data) return <Retry message={error} onRetry={() => void reload()} />;
  if (!data) return <p className="text-sm text-muted-foreground">در حال بارگذاری…</p>;

  const health = HEALTH_FA[data.health] ?? { label: data.health, tone: "text-muted-foreground" };
  const jobRows = Object.entries(data.jobs.by_status ?? {});

  return (
    <div className="space-y-4">
      <Surface className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-sm">
            وضعیت کلی: <span className={`font-bold ${health.tone}`} data-testid="overall">{health.label}</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            آخرین به‌روزرسانی: {updatedAt ? updatedAt.toLocaleTimeString("fa-IR") : "—"} · به‌روزرسانی خودکار هر ۱۰ ثانیه
          </p>
        </div>
        <button
          type="button"
          className="rounded-control border px-3 py-1.5 text-xs font-bold bg-primary text-primary-foreground hover:bg-primary/90"
          onClick={() => void reload()}
        >
          به‌روزرسانی
        </button>
      </Surface>

      {error && <p className="text-sm text-error">{error}</p>}

      <div className="grid gap-3 md:grid-cols-3">
        <Surface className="p-4 text-sm">
          <h2 className="text-xs font-bold text-muted-foreground">سرور برنامه</h2>
          <ul className="mt-2 space-y-1">
            <li>محیط اجرا: {data.environment ?? "—"}</li>
            <li>مدت کارکرد: {duration(data.uptime_seconds)}</li>
            <li>شناسهٔ فرایند: <span dir="ltr">{data.process?.pid ?? "—"}</span></li>
            <li>نخ‌های فعال: {data.process?.threads ?? "—"}</li>
            <li>
              میانگین بار (۱/۵/۱۵ دقیقه):{" "}
              <span dir="ltr">
                {[data.host?.load?.["1m"], data.host?.load?.["5m"], data.host?.load?.["15m"]]
                  .map((v) => (v === null || v === undefined ? "—" : v))
                  .join(" / ")}
              </span>
            </li>
          </ul>
        </Surface>

        <Surface className="p-4 text-sm">
          <h2 className="text-xs font-bold text-muted-foreground">پایگاه داده</h2>
          <ul className="mt-2 space-y-1">
            <li>وضعیت: {data.db.state === "up" ? "در دسترس" : "قطع"}</li>
            <li>تأخیر پاسخ: {data.db.latency_ms} میلی‌ثانیه</li>
            <li>اتصال‌های فعال: {data.db.connections ?? "—"}</li>
            <li>حجم پایگاه داده: {bytes(data.db.size_bytes)}</li>
            <li>
              نسخهٔ مایگریشن: <span dir="ltr">{data.db.migration_head ?? "—"}</span>
              {data.db.migrations_ok === false && <span className="text-error"> (با فایل‌های مایگریشن هم‌خوان نیست)</span>}
            </li>
          </ul>
        </Surface>

        <Surface className="p-4 text-sm">
          <h2 className="text-xs font-bold text-muted-foreground">فضای ذخیره‌سازی</h2>
          <ul className="mt-2 space-y-1">
            <li>مسیر: <span dir="ltr">{data.host?.disk?.root ?? "—"}</span></li>
            <li>فضای کل: {bytes(data.host?.disk?.total_bytes)}</li>
            <li>فضای آزاد: {bytes(data.host?.disk?.free_bytes)}</li>
            <li>حجم فایل‌های بارگذاری‌شده: {bytes(data.host?.disk?.uploads_bytes)}</li>
          </ul>
        </Surface>
      </div>

      <Surface className="p-4 text-sm">
        <h2 className="text-xs font-bold text-muted-foreground">صف پردازش</h2>
        <p className="mt-2">
          کارهای در جریان: <span className="font-bold" data-testid="jobs-open">{data.jobs.open}</span>
        </p>
        <p className="mt-1 text-xs text-muted-foreground" dir="ltr">
          {jobRows.length === 0 ? "—" : jobRows.map(([k, v]) => `${k}: ${v}`).join(" · ")}
        </p>
      </Surface>

      <Surface className="p-4 text-sm">
        <h2 className="text-xs font-bold text-muted-foreground">شمارنده‌ها</h2>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4">
          {Object.entries(data.counters ?? {}).map(([key, value]) => (
            <div key={key}>
              <dt className="text-[11px] text-muted-foreground">{COUNTER_FA[key] ?? key}</dt>
              <dd className="font-bold">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-muted-foreground">
          آخرین رویداد ثبت‌شده: {data.last_audit_at ? new Date(data.last_audit_at).toLocaleString("fa-IR") : "—"}
        </p>
      </Surface>

      <Surface className="p-4 text-sm">
        <h2 className="text-xs font-bold text-muted-foreground">سرویس‌های وابسته</h2>
        <ul className="mt-2 space-y-1">
          <li>مدل زبانی: <span dir="ltr">{data.llm_provider}</span></li>
          <li>پیامک: <span dir="ltr">{data.sms_provider}</span></li>
          <li>جست‌وجوی معنایی: <span dir="ltr">{data.embedding_provider}</span></li>
          {Object.entries(data.services ?? {}).map(([name, state]) => (
            <li key={name}>
              <span dir="ltr">{name}</span>: {state}
            </li>
          ))}
        </ul>
      </Surface>
    </div>
  );
}