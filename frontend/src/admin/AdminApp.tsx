import { useEffect, useState } from "react";

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

async function adminApi<T>(
  token: string,
  method: "GET" | "PUT" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(ADMIN_BASE + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = (await response.json()) as Envelope;
  if (!payload.success || payload.data === undefined) {
    throw new Error(payload.error?.message ?? "خطای ناشناخته");
  }
  return payload.data as T;
}

type Tab = "settings" | "orgs" | "requests" | "status";

const SETTING_KEYS = [
  { key: "providers_pricing", title: "درگاه مدل و قیمت", hint: "provider: mock | online-mock | openai-compatible" },
  { key: "models_allowlist", title: "لیست مدل‌های مجاز", hint: "مثال: {\"models\": [\"gpt-x\"], \"default\": \"gpt-x\"}" },
  { key: "pipeline", title: "پایپ‌لاین بازیابی", hint: "تنظیمات مرحلهٔ بازیابی دانش" },
  { key: "prompt_template", title: "قالب پرامپت", hint: "system + user_template با {question} و {context}" },
] as const;

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
      const payload = (await response.json()) as Envelope;
      const data = payload.data as { token?: string } | undefined;
      if (!payload.success || !data?.token) throw new Error(payload.error?.message ?? "ورود ناموفق");
      sessionStorage.setItem("hiveos.admin", data.token);
      setToken(data.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ورود ناموفق");
    }
  }

  if (!token) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <form
          onSubmit={login}
          className="w-full max-w-sm rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card"
          aria-label="ورود مدیر سامانه"
        >
          <h1 className="text-lg font-bold">پنل مدیریت HiveOS</h1>
          <label className="mt-4 block text-sm">
            نام کاربری
            <input
              className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-sm"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              dir="ltr"
              required
            />
          </label>
          <label className="mt-3 block text-sm">
            گذرواژه
            <input
              type="password"
              className="mt-1 w-full rounded-control border border-neutral-200 px-3 py-2 text-sm"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              dir="ltr"
              required
            />
          </label>
          {error && (
            <p role="alert" className="mt-3 text-sm text-red-700" data-testid="admin-error">
              {error}
            </p>
          )}
          <button className="mt-4 w-full rounded-control bg-navy-600 px-4 py-2 text-sm font-bold text-white">
            ورود
          </button>
        </form>
      </main>
    );
  }

  const tabs: ReadonlyArray<{ id: Tab; label: string }> = [
    { id: "settings", label: "تنظیمات" },
    { id: "orgs", label: "سازمان‌ها" },
    { id: "requests", label: "درخواست‌های شارژ" },
    { id: "status", label: "وضعیت سامانه" },
  ];

  return (
    <div className="min-h-dvh bg-neutral-50">
      <header className="border-b border-neutral-200 bg-neutral-0 px-4 py-2">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <h1 className="text-base font-bold">پنل مدیریت HiveOS</h1>
          <button
            type="button"
            className="text-sm text-neutral-600"
            onClick={() => {
              sessionStorage.removeItem("hiveos.admin");
              setToken(null);
            }}
          >
            خروج
          </button>
        </div>
      </header>
      <nav className="mx-auto mt-4 flex max-w-4xl gap-2 px-4" aria-label="بخش‌های پنل">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
            className={
              "rounded-control px-3 py-2 text-sm " +
              (tab === t.id ? "bg-navy-600 font-bold text-white" : "bg-neutral-0 text-neutral-600")
            }
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="mx-auto max-w-4xl px-4 py-4">
        {tab === "settings" && <SettingsTab token={token} />}
        {tab === "orgs" && <OrgsTab token={token} />}
        {tab === "requests" && <RequestsTab token={token} />}
        {tab === "status" && <StatusTab token={token} />}
      </main>
    </div>
  );
}

function SettingsTab({ token }: { token: string }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const loaded: Record<string, string> = {};
      for (const { key } of SETTING_KEYS) {
        try {
          const data = await adminApi<Record<string, unknown>>(token, "GET", "/settings/" + key);
          loaded[key] = JSON.stringify(data, null, 2);
        } catch {
          loaded[key] = "";
        }
      }
      setValues(loaded);
    })();
  }, [token]);

  async function save(key: string, text: string) {
    setError(null);
    setSaved(null);
    let parsed: unknown;
    try {
      parsed = text.trim() ? JSON.parse(text) : {};
    } catch {
      setError("JSON نامعتبر است.");
      return;
    }
    try {
      await adminApi(token, "PUT", "/settings/" + key, { value: parsed });
      setSaved(key);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ذخیره ناموفق");
    }
  }

  return (
    <div className="space-y-4">
      {SETTING_KEYS.map(({ key, title, hint }) => (
        <section key={key} className="rounded-card border border-neutral-200 bg-neutral-0 p-4">
          <h2 className="text-sm font-bold">{title}</h2>
          <p className="mt-1 text-xs text-neutral-500" dir="auto">
            {hint}
          </p>
          <textarea
            dir="ltr"
            rows={5}
            className="mt-2 w-full rounded-control border border-neutral-200 p-2 font-mono text-xs"
            aria-label={title}
            value={values[key] ?? ""}
            onChange={(e) => setValues({ ...values, [key]: e.target.value })}
          />
          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              className="rounded-control bg-navy-600 px-4 py-2 text-sm font-bold text-white"
              onClick={() => save(key, values[key] ?? "")}
            >
              ذخیره
            </button>
            {saved === key && <span className="text-sm text-green-700">ذخیره شد ✓</span>}
          </div>
        </section>
      ))}
      {error && (
        <p role="alert" className="text-sm text-red-700">
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
}

function OrgsTab({ token }: { token: string }) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [amounts, setAmounts] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const data = await adminApi<{ organizations: Org[] }>(token, "GET", "/organizations");
    setOrgs(data.organizations);
  }

  useEffect(() => {
    reload().catch(() => setMsg("دریافت سازمان‌ها ناموفق بود."));
  }, [token]);


  async function credit(orgId: string) {
    try {
      await adminApi(token, "POST", "/organizations/" + orgId + "/credit", {
        amount: amounts[orgId] ?? 0,
      });
      setMsg("اعتبار افزوده شد ✓");
      await reload();
    } catch {
      setMsg("افزودن اعتبار ناموفق بود.");
    }
  }

  return (
    <table className="w-full rounded-card border border-neutral-200 bg-neutral-0 text-sm">
      <thead>
        <tr className="border-b border-neutral-200 text-neutral-600">
          <th className="p-3 text-start">سازمان</th>
          <th className="p-3 text-start">موجودی</th>
          <th className="p-3 text-start">پلن</th>
          <th className="p-3 text-start">افزودن اعتبار</th>
        </tr>
      </thead>
      <tbody>
        {orgs.map((o) => (
          <tr key={o.id} className="border-b border-neutral-100">
            <td className="p-3 font-bold">{o.name}</td>
            <td className="p-3" data-testid={"balance-" + o.id}>
              {o.balance}
            </td>
            <td className="p-3 text-xs">
              {o.plan ?? "trial"}
              {o.plan_expires_at && (
                <span dir="ltr" className="block text-neutral-500">
                  {new Date(o.plan_expires_at).toISOString().slice(0, 10)}
                </span>
              )}
            </td>
            <td className="p-3">
              <div className="flex gap-2">
                <input
                  type="number"
                  min={1}
                  aria-label={"مبلغ برای " + o.name}
                  className="w-24 rounded-control border border-neutral-200 px-2 py-1"
                  value={amounts[o.id] ?? ""}
                  onChange={(e) => setAmounts({ ...amounts, [o.id]: Number(e.target.value) })}
                />
                <button
                  type="button"
                  className="rounded-control bg-navy-600 px-3 py-1 font-bold text-white"
                  onClick={() => credit(o.id)}
                >
                  اعمال
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
      {msg && (
        <tfoot>
          <tr>
            <td colSpan={4} className="p-3 text-green-700">
              {msg}
            </td>
          </tr>
        </tfoot>
      )}
    </table>
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

  async function reload() {
    const data = await adminApi<{ requests: ChargeRequestItem[] }>(
      token,
      "GET",
      "/charge-requests",
    );
    setItems(data.requests);
  }

  useEffect(() => {
    reload().catch(() => setMsg("دریافت درخواست‌ها ناموفق بود."));
  }, [token]);

  async function decide(id: string, approve: boolean) {
    try {
      await adminApi(token, "POST", "/charge-requests/" + id + "/decision", { approve });
      await reload();
      setMsg(approve ? "تأیید شد و اعتبار افزوده شد ✓" : "رد شد ✓");
    } catch {
      setMsg("عملیات ناموفق بود.");
    }
  }

  return (
    <div className="space-y-3">
      {msg && <p className="text-sm text-green-700">{msg}</p>}
      {items.length === 0 && <p className="text-sm text-neutral-600">درخواستی ثبت نشده است.</p>}
      {items.map((r) => (
        <div
          key={r.id}
          className="flex items-center justify-between rounded-card border border-neutral-200 bg-neutral-0 p-4"
        >
          <div className="text-sm">
            <p className="font-bold" dir="ltr">
              {r.amount} — {r.status}
            </p>
            {r.note && <p className="text-xs text-neutral-500">{r.note}</p>}
          </div>
          {r.status === "PENDING" && (
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-control bg-green-600 px-3 py-1 text-sm font-bold text-white"
                onClick={() => decide(r.id, true)}
              >
                تأیید
              </button>
              <button
                type="button"
                className="rounded-control bg-red-600 px-3 py-1 text-sm font-bold text-white"
                onClick={() => decide(r.id, false)}
              >
                رد
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

interface SystemStatus {
  overall: string;
  checks: Array<{ check: string; status: string; detail?: string }>;
}

function StatusTab({ token }: { token: string }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    adminApi<SystemStatus>(token, "GET", "/system-status")
      .then(setStatus)
      .catch(() => setStatus({ overall: "ERROR", checks: [] }));
  }, [token]);

  if (!status) return <p className="text-sm text-neutral-600">در حال بارگذاری…</p>;
  return (
    <div className="rounded-card border border-neutral-200 bg-neutral-0 p-4">
      <p className="text-sm">
        وضعیت کلی:{" "}
        <span className="font-bold" data-testid="overall">
          {status.overall}
        </span>
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {status.checks.map((c) => (
          <li key={c.check}>
            {c.check}: {c.status}
          </li>
        ))}
      </ul>
    </div>
  );
}
