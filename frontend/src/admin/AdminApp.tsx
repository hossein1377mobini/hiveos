import { Suspense, lazy, useEffect, useState } from "react"
import {
  BotIcon,
  BuildingIcon,
  CreditCardIcon,
  GaugeIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  ReceiptIcon,
  ScrollTextIcon,
  SearchIcon,
  SettingsIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"

import { Button } from "../components/ui/button"
import { ErrorText } from "../components/ui/error-text"
import { Field } from "../components/auth/parts"
import { Input } from "../components/ui/input"
import { CommandPalette, useCommandPalette, type CommandItem } from "../components/ui/command-palette"
import { RouteFallback } from "../components/RouteFallback"
import { Toaster } from "../components/ui/sonner"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "../components/ui/breadcrumb"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "../components/ui/sidebar"
import { persianError } from "../api/errors"
import {
  ADMIN_BASE,
  AdminSessionExpired,
  adminApi,
  readEnvelope,
  setAdminSessionExpiredHandler,
} from "./api"

/**
 * Admin panel shell.
 *
 * v0.1 was one 1243-line file rendering six flat tabs with no URL of their own:
 * an operator could not link a colleague to an organisation, refresh without
 * losing their place, or use the browser Back button. It also hand-rolled its
 * own buttons and inputs next to the design system, so the panel looked like a
 * different product from the app it administers. [A1/D3/A3]
 *
 * Each workspace is a lazy route now, the chrome is the same Sidebar + Breadcrumb
 * the organisation app uses, and every control comes from components/ui.
 */

export interface AdminWorkspace {
  id: string
  path: string
  label: string
  description: string
  icon: LucideIcon
  keywords: string[]
}

export const ADMIN_WORKSPACES: AdminWorkspace[] = [
  {
    id: "overview",
    path: "/admin",
    label: "نمای کلی",
    description: "تصویر یک‌نگاه از سامانه",
    icon: LayoutDashboardIcon,
    keywords: ["خلاصه", "داشبورد", "وضعیت"],
  },
  {
    id: "organizations",
    path: "/admin/organizations",
    label: "سازمان‌ها",
    description: "کاربران، اعتبار و فضای هر سازمان",
    icon: BuildingIcon,
    keywords: ["مشتری", "کاربر", "اعتبار", "حذف"],
  },
  {
    id: "billing",
    path: "/admin/billing",
    label: "مالی و اشتراک",
    description: "درخواست‌های شارژ، پلن‌ها و قیمت‌گذاری",
    icon: CreditCardIcon,
    keywords: ["شارژ", "پرداخت", "پلن", "کیف پول"],
  },
  {
    id: "operations",
    path: "/admin/operations",
    label: "پایش عملیات",
    description: "سرور، پشتیبان‌گیری و صف پردازش",
    icon: GaugeIcon,
    keywords: ["سرور", "پشتیبان", "دیسک", "حافظه", "بکاپ"],
  },
  {
    id: "ai",
    path: "/admin/ai",
    label: "هوش مصنوعی",
    description: "درگاه، مدل‌ها و اعتبار حساب هوش مصنوعی",
    icon: SettingsIcon,
    keywords: ["مدل", "درگاه", "کلید", "اعتبار", "پرامپت"],
  },
  {
    id: "agents",
    path: "/admin/agents",
    label: "ایجنت‌ها",
    description: "ایجنت هر کاربر، حافظه و ابزارهایش",
    icon: BotIcon,
    keywords: ["ایجنت", "حافظه", "ابزار", "نمودار", "گزارش", "شخصیت"],
  },
  {
    id: "events",
    path: "/admin/events",
    label: "رویدادها",
    description: "ردیابی فعالیت‌ها و خطاها",
    icon: ScrollTextIcon,
    keywords: ["لاگ", "خطا", "فعالیت", "گزارش"],
  },
  {
    id: "system",
    path: "/admin/system",
    label: "وضعیت سامانه",
    description: "سالم بودن سرویس‌ها و شمارنده‌ها",
    icon: ReceiptIcon,
    keywords: ["سلامت", "دیتابیس", "سرویس", "شمارنده"],
  },
]

export function workspaceFor(pathname: string): AdminWorkspace {
  // Longest match wins: /admin/organizations must not be shadowed by /admin.
  const sorted = [...ADMIN_WORKSPACES].sort((a, b) => b.path.length - a.path.length)
  return sorted.find((w) => pathname === w.path || pathname.startsWith(w.path + "/")) ?? ADMIN_WORKSPACES[0]
}

const OverviewView = lazy(() => import("./views/OverviewView"))
const OrganizationsView = lazy(() => import("./views/OrganizationsView"))
const BillingView = lazy(() => import("./views/BillingView"))
const OperationsView = lazy(() => import("./views/OperationsView"))
const AiView = lazy(() => import("./views/AiView"))
const EventsView = lazy(() => import("./views/EventsView"))
const AgentsView = lazy(() => import("./views/AgentsView"))
const SystemView = lazy(() => import("./views/SystemView"))

export default function AdminApp() {
  const location = useLocation()

  return (
    <AdminGate>
      {(token) => (
        <>
          <AdminFrame pathname={location.pathname} token={token}>
            <Suspense fallback={<RouteFallback />}>
              <AdminRoutes token={token} />
            </Suspense>
          </AdminFrame>
          {/* The toast surface lives here rather than in main.tsx on purpose.
              Every toast call site is inside the admin panel (AiView,
              BillingView, OrganizationsView), yet mounting <Toaster/> at the
              app root pulled sonner into the entry chunk - 47.5 kB minified /
              13.4 kB gzipped on the critical path for every visitor, including
              the login page, which can never raise a toast. AdminApp is already
              lazily imported, so mounting it here moves that cost to the only
              users who can trigger it. [perf audit] */}
          <Toaster />
        </>
      )}
    </AdminGate>
  )
}

function AdminRoutes({ token }: { token: string }) {
  const location = useLocation()
  const workspace = workspaceFor(location.pathname)

  switch (workspace.id) {
    case "organizations":
      return <OrganizationsView token={token} />
    case "billing":
      return <BillingView token={token} />
    case "operations":
      return <OperationsView token={token} />
    case "ai":
      return <AiView token={token} />
    case "agents":
      return <AgentsView token={token} />
    case "events":
      return <EventsView token={token} />
    case "system":
      return <SystemView token={token} />
    default:
      return <OverviewView token={token} />
  }
}

/**
 * Login gate. Kept as a render prop so the frame below only ever runs with a
 * real token and never has to branch on null.
 */
function AdminGate({ children }: { children: (token: string) => React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem("hiveos.admin"))
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setAdminSessionExpiredHandler(() => {
      sessionStorage.removeItem("hiveos.admin")
      setToken(null)
      setError("نشست مدیر منقضی شده است؛ دوباره وارد شوید.")
    })
    return () => setAdminSessionExpiredHandler(null)
  }, [])

  async function login(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const response = await fetch(ADMIN_BASE + "/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      })
      const payload = await readEnvelope(response)
      const data = payload?.data as { token?: string } | undefined
      if (payload === null || !payload.success || !data?.token) {
        throw new Error(
          persianError(
            payload?.error?.code ?? "CLIENT_BAD_RESPONSE",
            response.status,
            payload?.error?.message,
          ),
        )
      }
      sessionStorage.setItem("hiveos.admin", data.token)
      setToken(data.token)
    } catch (err) {
      setError(err instanceof Error ? err.message : "ورود ناموفق بود.")
    } finally {
      setBusy(false)
    }
  }

  if (token) return <>{children(token)}</>

  return (
    <main className="flex min-h-dvh items-center justify-center bg-secondary px-4">
      <form
        onSubmit={login}
        className="w-full max-w-sm rounded-card border border-border bg-card p-6 shadow-raised"
        aria-label="ورود مدیر سامانه"
      >
        <h1 className="text-title">پنل مدیریت HiveOS</h1>
        <p className="mt-1 text-caption text-muted-foreground">
          این بخش مخصوص مدیر سامانه است. دسترسی‌ها اینجا ثبت می‌شود.
        </p>
        <Field label="نام کاربری" htmlFor="admin-username" className="mb-0 mt-5">
          <Input
            id="admin-username"
            className="rounded-control text-caption"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            dir="ltr"
            autoComplete="username"
            required
          />
        </Field>
        <Field label="گذرواژه" htmlFor="admin-password" className="mb-0 mt-3">
          <Input
            id="admin-password"
            type="password"
            className="rounded-control text-caption"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            dir="ltr"
            autoComplete="current-password"
            required
          />
        </Field>
        <ErrorText className="mt-3" data-testid="admin-error">
          {error}
        </ErrorText>
        <Button type="submit" className="mt-5 w-full" disabled={busy}>
          {busy ? "در حال ورود…" : "ورود"}
        </Button>
      </form>
    </main>
  )
}

function AdminFrame({
  pathname,
  token,
  children,
}: {
  pathname: string
  token: string
  children: React.ReactNode
}) {
  const navigate = useNavigate()
  const palette = useCommandPalette()
  const workspace = workspaceFor(pathname)

  const commands: CommandItem[] = ADMIN_WORKSPACES.map((w) => ({
    id: "admin-" + w.id,
    label: w.label,
    group: "پنل مدیریت",
    path: w.path,
    icon: w.icon,
    keywords: [...w.keywords, w.description],
  }))

  async function logout() {
    // Dropping the browser copy is not a logout on its own: the token also
    // lives in hiveos.admin_sessions, where it stayed valid for the full
    // session TTL (12h by default). Anyone who had copied it kept full
    // /api/v1/admin access after the operator believed they had signed out.
    // POST /admin/auth/logout is what actually revokes the row. It is awaited
    // with a short leash: a network failure must still drop the local session
    // rather than trap the operator in the panel.
    try {
      await adminApi(token, "POST", "/auth/logout")
    } catch {
      // Revocation is best-effort; the local token is discarded either way.
    }
    sessionStorage.removeItem("hiveos.admin")
    // A full reload is correct here: it drops every cached admin view's state,
    // including the polling hooks, before the login form renders.
    window.location.href = "/admin"
  }

  return (
    // h-svh + min-h-0 for the same reason as the organisation shell: a
    // minimum-height wrapper grows to the content, so the admin document
    // scrolled as a whole and the sidebar stretched past the viewport.
    <SidebarProvider className="h-svh min-h-0">
      <Sidebar side="right" collapsible="icon" className="border-e border-sidebar-border">
        <SidebarHeader className="flex-row items-center gap-2.5 px-2 py-3.5">
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-control bg-sidebar-primary text-sidebar-primary-foreground"
          >
            <SettingsIcon className="size-4.5" />
          </span>
          <span className="grid min-w-0 flex-1 leading-tight">
            <span className="truncate text-subheading font-bold text-sidebar-foreground">
              مدیریت HiveOS
            </span>
            <span className="truncate text-micro text-muted-foreground">مدیر سامانه</span>
          </span>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="text-micro font-bold">
              بخش‌های پنل
            </SidebarGroupLabel>
            <SidebarMenu>
              {ADMIN_WORKSPACES.map((w) => {
                // Same defect as the organisation shell: SidebarMenuButton
                // hard-codes data-active from its own prop (default false), so
                // the panel had no visible current section at all.
                const isActive =
                  w.path === "/admin"
                    ? pathname === "/admin" || pathname === "/admin/"
                    : pathname === w.path || pathname.startsWith(w.path + "/")
                return (
                  <SidebarMenuItem key={w.id}>
                    <SidebarMenuButton asChild isActive={isActive} tooltip={w.label}>
                      <NavLink
                        to={w.path}
                        end={w.path === "/admin"}
                        className="h-auto py-2 text-caption font-medium data-[active=true]:font-bold [&[data-active=true]>svg]:text-sidebar-accent-foreground"
                      >
                        <w.icon aria-hidden />
                        <span>{w.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="border-t border-sidebar-border">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={logout}
                tooltip="خروج از پنل"
                className="h-auto py-2 text-caption text-muted-foreground"
              >
                <LogOutIcon aria-hidden className="rtl:-scale-x-100" />
                <span>خروج از پنل</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2.5 border-b border-border bg-background/95 px-4 backdrop-blur-sm">
          <SidebarTrigger aria-label="نمایش یا پنهان کردن ناوبری" />
          <Breadcrumb className="min-w-0">
            <BreadcrumbList className="flex-nowrap text-caption">
              <BreadcrumbItem className="hidden sm:inline-flex">
                <span className="text-muted-foreground">پنل مدیریت</span>
              </BreadcrumbItem>
              <BreadcrumbSeparator className="hidden sm:inline-flex rtl:-scale-x-100">
                <span aria-hidden>/</span>
              </BreadcrumbSeparator>
              <BreadcrumbItem className="min-w-0">
                <BreadcrumbPage className="truncate font-bold text-foreground">
                  {workspace.label}
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <div className="ms-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => palette.setOpen(true)}
              className="hidden rounded-control text-muted-foreground md:inline-flex"
              aria-keyshortcuts="Control+K"
            >
              <SearchIcon className="size-3.5" />
              جستجوی بخش
              <kbd className="mono ms-1 rounded-xs border border-border bg-secondary px-1 py-px text-micro">
                Ctrl K
              </kbd>
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="rounded-control"
              onClick={() => navigate("/chat")}
            >
              نمای سازمان
            </Button>
          </div>
        </header>
        {/* min-h-0 + overflow-y-auto: same defect as the organisation shell.
            Without them <main> is sized by its content, so the document scrolled
            as a whole and the sidebar rail stretched past the viewport on every
            tall admin view. Now the panel body scrolls inside the frame. */}
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto px-6 pb-14 pt-6">
          <div className="mx-auto grid max-w-6xl gap-5">
            {/* The shell owns the h1: a view that repeated it would render two
                level-one headings, and one that used h2 for its page title
                would leave the document without a level-one heading at all.
                Every workspace below the title now shares this one gap. */}
            <div>
              <h1 className="text-title">{workspace.label}</h1>
              <p className="mt-1 text-caption text-muted-foreground">{workspace.description}</p>
            </div>
            {children}
          </div>
        </main>
      </SidebarInset>

      <CommandPalette items={commands} open={palette.open} onOpenChange={palette.setOpen} />
    </SidebarProvider>
  )
}

export { AdminSessionExpired }
