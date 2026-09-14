import { Suspense, lazy, useEffect, useState } from "react"
import { Navigate, Route, Routes, useNavigate } from "react-router-dom"

import { AppShell, type NavId } from "./components/AppShell"
import { SessionIdentityProvider, useSessionIdentity } from "./lib/identity-context"
import { ErrorBoundary } from "./components/ErrorBoundary"
import { RouteFallback } from "./components/RouteFallback"
import { Button } from "./components/ui/button"
import { Surface } from "./components/ui/surface"
import { api, clearToken, getToken } from "./api/client"
import type { SessionIdentity } from "./lib/session"

/**
 * Route-level code splitting.
 *
 * v0.1 shipped one 604 kB bundle: the admin panel, the chat client, the OCR
 * upload path and every onboarding screen were parsed before the login form
 * could paint. Each surface is loaded when its route is first visited. [A6]
 */
const Login = lazy(() => import("./pages/Login"))
const RegisterOrganization = lazy(() => import("./pages/RegisterOrganization"))
const OwnerAccount = lazy(() => import("./pages/OwnerAccount"))
const OtpVerify = lazy(() => import("./pages/OtpVerify"))
const Onboarding = lazy(() => import("./pages/Onboarding"))
const Wallet = lazy(() => import("./pages/Wallet"))
const Usage = lazy(() => import("./pages/Usage"))
const Chat = lazy(() => import("./pages/Chat"))
const Knowledge = lazy(() => import("./pages/Knowledge"))
const Agent = lazy(() => import("./pages/Agent"))
const Subscription = lazy(() => import("./pages/Subscription"))
const AdminApp = lazy(() => import("./admin/AdminApp"))

/**
 * Application routing.
 *
 * v0.1 kept the current screen in useState and detected the admin panel with
 * window.location.pathname.startsWith("/admin"). That made every section
 * unreachable by URL, broke refresh and the browser Back button, and blocked any
 * deep link such as /admin/orgs/:id. [A4/A5/D1]
 *
 * The router owns navigation now. The server still owns the onboarding decision:
 * GET /auth/onboarding-status says which step comes next, the router lands on
 * the answer it gives.
 */

interface OnboardingStatus {
  organization_status: string
  next_step: string
  /** Returned by the API since H1 closed; the shell reads it via identity-context. */
  identity?: SessionIdentity | null
}

/** Session token lives in localStorage; the guard reads it on every route. */
function RequireSession({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return <>{children}</>
}

/**
 * Frame for the eight unauthenticated screens (login, register, owner, OTP,
 * onboarding, expired, offline).
 *
 * The inner div is a <main> landmark rather than a plain div: axe's
 * landmark-one-main rule is page-scope, so running axe against a render
 * container (as the jsdom suite does) never checks it - every auth screen could
 * ship with no landmark and the accessibility gate stayed green. Found by the
 * browser e2e suite, which is the only test that sees a whole page.
 */
function CenteredAuth({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-start justify-center bg-secondary px-4 pb-16 pt-11">
      <main className="w-full max-w-[700px]">{children}</main>
    </div>
  )
}

/**
 * The owner step needs the organization id the signup flow created. Persisted in
 * sessionStorage so a refresh or a Back navigation mid-signup does not lose it.
 */
function readPendingOrganizationId(): string | null {
  try {
    return sessionStorage.getItem("hiveos.pending_organization")
  } catch {
    return null
  }
}

/** The admin panel: its own surface, its own login, its own chrome. */
function AdminSurface() {
  return (
    <ErrorBoundary title="خطا در پنل مدیریت">
      <Suspense fallback={<RouteFallback label="در حال بارگذاری پنل مدیریت…" />}>
        <AdminApp />
      </Suspense>
    </ErrorBoundary>
  )
}

export default function App() {
  return (
    // One identity load for the whole authenticated app; the shell reads it from
    // here instead of each route fetching its own copy. [D10/H1]
    <SessionIdentityProvider>
    <Suspense fallback={<RouteFallback />}>
    <Routes>
      {/*
        The admin panel used to be mounted by testing
        window.location.pathname.startsWith("/admin") ahead of the router. That
        read the URL once per document load, so an in-app navigation into
        /admin* (a sidebar link, the command palette) never re-evaluated it and
        the panel only appeared after a full reload. It is a route like any
        other now; the panel's own nested routes live inside AdminApp.
      */}
      <Route path="/admin/*" element={<AdminSurface />} />
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/register" element={<RegisterRoute />} />
      {/*
        Reachable without a session on purpose: the owner form is what creates
        one. Guarding it would send every new signup back to /login.
      */}
      <Route path="/owner" element={<OwnerRoute />} />
      {/*
        The landing route is the bootstrap decision, not a screen of its own:
        it asks the server where the organisation is in the flow and moves on.
      */}
      <Route
        path="/"
        element={
          <RequireSession>
            <BootstrapRoute />
          </RequireSession>
        }
      />
      <Route
        path="/chat"
        element={
          <RequireSession>
            <ShellRoutes screen="chat" />
          </RequireSession>
        }
      />
      <Route
        path="/agent"
        element={
          <RequireSession>
            <ShellRoutes screen="agent" />
          </RequireSession>
        }
      />
      <Route
        path="/knowledge"
        element={
          <RequireSession>
            <ShellRoutes screen="knowledge" />
          </RequireSession>
        }
      />
      <Route
        path="/usage"
        element={
          <RequireSession>
            <ShellRoutes screen="usage" />
          </RequireSession>
        }
      />
      <Route
        path="/wallet"
        element={
          <RequireSession>
            <ShellRoutes screen="wallet" />
          </RequireSession>
        }
      />
      <Route
        path="/subscription"
        element={
          <RequireSession>
            <ShellRoutes screen="subscription" />
          </RequireSession>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
    </SessionIdentityProvider>
  )
}

/* --- Auth routes ----------------------------------------------------------- */

function LoginRoute() {
  const navigate = useNavigate()
  return (
    <CenteredAuth>
      <Login onDone={() => navigate("/", { replace: true })} />
      <p className="mx-auto mt-3 max-w-md text-center text-caption text-muted-foreground">
        حساب سازمان ندارید؟{" "}
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0 font-bold text-primary"
          onClick={() => navigate("/register")}
        >
          ساخت سازمان جدید
        </Button>
      </p>
    </CenteredAuth>
  )
}

/**
 * Step 2 of signup: the owner account.
 *
 * It is its own route rather than a state inside the bootstrap, because the
 * bootstrap asks /auth/onboarding-status and that call needs a session — and
 * this step is exactly where the session is created. Routing to "/" right after
 * the organization was created bounced the user straight to /login:
 * RequireSession found no token, and there is none to find until POST
 * /auth/owner succeeds further down this screen. That was the "signup throws me
 * out midway" report.
 */
function OwnerRoute() {
  const navigate = useNavigate()
  const organizationId = readPendingOrganizationId()

  if (!organizationId) {
    return (
      <CenteredAuth>
        <Surface className="mx-auto max-w-md text-center">
          <h1 className="text-heading">ادامهٔ ثبت‌نام از این مرورگر ممکن نیست</h1>
          <p className="mt-2 text-caption text-muted-foreground">
            شناسهٔ سازمان در این مرورگر موجود نیست. لطفاً فرایند ساخت سازمان را از ابتدا
            آغاز کنید.
          </p>
          <Button className="mt-4" onClick={() => navigate("/register")}>
            ساخت سازمان جدید
          </Button>
        </Surface>
      </CenteredAuth>
    )
  }

  return (
    <CenteredAuth>
      <OwnerAccount
        organizationId={organizationId}
        // OwnerAccount stores the session token before calling this, so the
        // bootstrap can now read the real onboarding status.
        onDone={() => navigate("/", { replace: true })}
        onBack={() => navigate("/register")}
      />
    </CenteredAuth>
  )
}

function RegisterRoute() {
  const navigate = useNavigate()
  return (
    <CenteredAuth>
      <RegisterOrganization
        onCreated={() => navigate("/owner", { replace: true })}
        onBack={() => navigate("/login")}
      />
    </CenteredAuth>
  )
}

/* --- Bootstrap ------------------------------------------------------------- */

type BootstrapState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "owner" }
  | { kind: "otp" }
  | { kind: "wizard" }
  | { kind: "expired" }
  | { kind: "done"; identity: SessionIdentity | null }

/**
 * Reads the server's answer once and renders the matching surface.
 *
 * An unknown step is treated as "done" rather than as an error: the backend is
 * allowed to add steps, and stranding every existing organisation on a spinner
 * because the client did not recognise a new value would be worse than landing
 * them in the app.
 */
function BootstrapRoute() {
  const navigate = useNavigate()
  const [state, setState] = useState<BootstrapState>({ kind: "loading" })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const status = await api<OnboardingStatus>("GET", "/auth/onboarding-status")
        if (cancelled) return
        switch (status.next_step) {
          case "owner":
            setState({ kind: "owner" })
            break
          // The server reports "otp" for an organization whose owner exists but
          // whose mobile is still unverified. Nothing rendered this step before,
          // so the flow dead-ended here: verify-otp is the only endpoint that
          // activates the organization.
          case "otp":
            setState({ kind: "otp" })
            break
          case "workspace":
          case "brain":
          case "knowledge_source":
            setState({ kind: "wizard" })
            break
          case "expired":
            setState({ kind: "expired" })
            break
          case "chat":
            navigate("/chat", { replace: true })
            break
          default:
            setState({ kind: "done", identity: status.identity ?? null })
        }
      } catch {
        if (!cancelled) setState({ kind: "error" })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [navigate])

  if (state.kind === "loading") {
    return (
      <CenteredAuth>
        <Surface className="mx-auto max-w-md text-center">
          <p className="text-caption text-muted-foreground">در حال بررسی وضعیت سازمان…</p>
        </Surface>
      </CenteredAuth>
    )
  }

  if (state.kind === "error") {
    return (
      <CenteredAuth>
        <Surface className="mx-auto max-w-md text-center">
          <h1 className="text-heading">دریافت وضعیت سازمان ناموفق بود</h1>
          <p className="mt-2 text-caption text-muted-foreground">
            اتصال به سرور برقرار نشد. صفحه را دوباره بارگذاری کنید.
          </p>
          <Button className="mt-4" onClick={() => window.location.reload()}>
            بارگذاری دوباره
          </Button>
        </Surface>
      </CenteredAuth>
    )
  }

  if (state.kind === "expired") {
    return (
      <CenteredAuth>
        <Surface className="mx-auto max-w-md">
          <h1 className="text-heading text-error">ثبت‌نام این سازمان منقضی شد</h1>
          <p className="mt-2 text-caption text-muted-foreground">
            سازمان در بازهٔ مجاز تکمیل نشد. برای ادامه، فرایند ساخت سازمان را از ابتدا
            آغاز کنید.
          </p>
          <Button
            variant="secondary"
            className="mt-4"
            onClick={() => {
              clearToken()
              navigate("/register", { replace: true })
            }}
          >
            ساخت سازمان جدید
          </Button>
        </Surface>
      </CenteredAuth>
    )
  }

  if (state.kind === "owner") {
    const organizationId = readPendingOrganizationId()
    if (!organizationId) {
      return (
        <CenteredAuth>
          <Surface className="mx-auto max-w-md text-center">
            <h1 className="text-heading">ادامهٔ ثبت‌نام از این مرورگر ممکن نیست</h1>
            <p className="mt-2 text-caption text-muted-foreground">
              شناسهٔ سازمان در این مرورگر موجود نیست. لطفاً فرایند ساخت سازمان را از ابتدا
              آغاز کنید.
            </p>
            <Button className="mt-4" onClick={() => navigate("/register")}>
              ساخت سازمان جدید
            </Button>
          </Surface>
        </CenteredAuth>
      )
    }
    return (
      <CenteredAuth>
        <OwnerAccount
          organizationId={organizationId}
          onDone={() => setState({ kind: "otp" })}
          onBack={() => navigate("/register")}
        />
      </CenteredAuth>
    )
  }

  if (state.kind === "otp") {
    return (
      <CenteredAuth>
        <OtpVerify
          // The mobile is now verified and the organization active, so the
          // wizard can run against a real, resumable status.
          onVerified={() => setState({ kind: "wizard" })}
          onBack={() => navigate("/")}
        />
      </CenteredAuth>
    )
  }

  if (state.kind === "done") {
    return (
      <AppShell identity={state.identity}>
        <Surface className="mx-auto max-w-xl">
          <h1 className="text-heading">راه‌اندازی سازمان کامل شد</h1>
          <p className="mt-2 text-caption text-muted-foreground">
            از فهرست کنار صفحه، گفتگو با هوش سازمان را آغاز کنید.
          </p>
          <Button className="mt-4" onClick={() => navigate("/chat")}>
            رفتن به گفتگو
          </Button>
        </Surface>
      </AppShell>
    )
  }

  return (
    <CenteredAuth>
      <Onboarding
        onStatus={(status) => {
          if (status.next_step === "chat") navigate("/chat", { replace: true })
        }}
      />
    </CenteredAuth>
  )
}

/* --- Organisation shell ---------------------------------------------------- */

/**
 * One shell instance per route. The screen is passed explicitly rather than
 * inferred from the path, so an unknown URL cannot silently render a section
 * that the address bar does not name.
 */
function ShellRoutes({ screen }: { screen: NavId }) {
  const navigate = useNavigate()
  // The identity the header shows. Read from the shared context so the five
  // sibling routes all get it without the router threading it through. [D10/H1]
  const identity = useSessionIdentity()
  const go = (id: NavId) => navigate("/" + id)

  return (
    <AppShell identity={identity} flush={screen === "chat"}>
      {screen === "wallet" ? (
        <Wallet />
      ) : screen === "chat" ? (
        <Chat />
      ) : screen === "agent" ? (
        <Agent />
      ) : screen === "knowledge" ? (
        <Knowledge />
      ) : screen === "subscription" ? (
        <Subscription onNavigate={(id) => go(id as NavId)} />
      ) : (
        <Usage />
      )}
    </AppShell>
  )
}
