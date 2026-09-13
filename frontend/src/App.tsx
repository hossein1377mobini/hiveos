import { useEffect, useState } from "react";
import { AppShell, type NavId } from "./components/AppShell";
import { Button } from "./components/ui/button";
import { api, getToken } from "./api/client";
import Login from "./pages/Login";
import RegisterOrganization from "./pages/RegisterOrganization";
import OwnerAccount from "./pages/OwnerAccount";
import OtpVerify from "./pages/OtpVerify";
import Onboarding from "./pages/Onboarding";
import Wallet from "./pages/Wallet";
import Chat from "./pages/Chat";
import Knowledge from "./pages/Knowledge";
import Subscription from "./pages/Subscription";
import AdminApp from "./admin/AdminApp";
import { Surface } from "./components/ui/surface";

interface Status {
  organization_status: string;
  next_step: string;
}

type Screen =
  | "login"
  | "register"
  | "owner"
  | "otp"
  | "onboarding"
  | "chat"
  | "wallet"
  | "knowledge"
  | "usage"
  | "subscription";

// T-S1-9: bootstrap mockups wired to the API. Step selection follows the server
// (onboarding-status.next_step), not client-side guesses (C2 resume semantics).
export default function App() {
  const [screen, setScreen] = useState<Screen | null>(null);
  const [organizationId, setOrganizationId] = useState<string | null>(null);

  // Admin panel rides the same SPA under /admin (epic-16). Checked before the
  // effect but the effect stays unconditional (Rules of Hooks).
  const isAdmin = window.location.pathname.startsWith("/admin");

  useEffect(() => {
    if (isAdmin) return;
    (async () => {
      if (!getToken()) {
        setScreen("login");
        return;
      }
      try {
        const status = await api<Status>("GET", "/auth/onboarding-status");
        routeFromStatus(status.next_step);
      } catch {
        setScreen("login");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  function routeFromStatus(nextStep: string) {
    if (nextStep === "owner") setScreen("owner");
    else if (nextStep === "expired") setScreen("onboarding");
    else if (nextStep === "workspace" || nextStep === "brain" || nextStep === "knowledge_source")
      setScreen("onboarding");
    else if (nextStep === "chat") setScreen("chat");
    else setScreen("login");
  }

  if (isAdmin) return <AdminApp />;

  if (screen === null) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-secondary">
        <p className="text-sm text-muted-foreground">در حال بارگذاری…</p>
      </div>
    );
  }

  // Auth screens (00–03 mockups) are standalone .auth-body pages WITHOUT the
  // app shell — the shell (10-app-shell.html) only appears after onboarding.
  if (screen === "login" || screen === "register" || screen === "owner" || screen === "otp") {
    return (
      <div className="flex min-h-dvh items-start justify-center bg-secondary px-4 pb-16 pt-11">
        <div className="w-full max-w-[700px]">
          {screen === "login" && (
            <>
              <Login onDone={() => setScreen("onboarding")} />
              <p className="mx-auto mt-3 max-w-md text-center text-[13px] text-muted-foreground">
                حساب سازمان ندارید؟{" "}
                <Button variant="link" size="sm" className="h-auto p-0 font-bold text-primary" onClick={() => setScreen("register")}>
                  ساخت سازمان جدید
                </Button>
              </p>
            </>
          )}
          {screen === "register" && (
            <RegisterOrganization
              onCreated={(organizationId) => {
                setOrganizationId(organizationId);
                setScreen("owner");
              }}
              onBack={() => setScreen("login")}
            />
          )}
          {screen === "owner" && (
            <OwnerAccount
              organizationId={organizationId ?? ""}
              onDone={() => setScreen("otp")}
              onBack={() => setScreen("register")}
            />
          )}
          {screen === "otp" && (
            <OtpVerify
              onVerified={() => setScreen("onboarding")}
              onBack={() => setScreen("owner")}
            />
          )}
        </div>
      </div>
    );
  }

  // Onboarding steps 04–07 are also standalone .auth-body pages (stepper on top,
  // no shell) — mockups 04-workspace-init … 07-onboarding-complete.
  if (screen === "onboarding") {
    return (
      <div className="flex min-h-dvh items-start justify-center bg-secondary px-4 pb-16 pt-11">
        <div className="w-full max-w-[700px]">
          <Onboarding onStatus={(status) => { if (status.next_step === "chat") setScreen("chat"); }} />
        </div>
      </div>
    );
  }

  return (
    <AppShell
      active={screen as NavId}
      onNavigate={(id: NavId) =>
        // F: every id used to fall back to "chat", so «اعتبار و مصرف» silently
        // opened the chat page while still highlighting itself in the sidebar.
        setScreen(id)
      }
    >
      {screen === "wallet" ? (
        <Wallet />
      ) : screen === "chat" ? (
        <Chat />
      ) : screen === "knowledge" ? (
        <Knowledge />
      ) : screen === "subscription" ? (
        <Subscription onNavigate={(id) => setScreen(id as Screen)} />
      ) : screen === "usage" ? (
        <Surface className="mx-auto max-w-xl p-6">
          <h1 className="text-lg font-bold">اعتبار و مصرف</h1>
          <p className="mt-2 text-sm leading-[1.9] text-muted-foreground">
            گزارش تفصیلی مصرف در نسخه‌ی بعدی اسپرینت‌ها اضافه می‌شود. موجودی و تراکنش‌ها همین حالا
            در «کیف پول» قابل مشاهده است.
          </p>
        </Surface>
      ) : (
        <Surface className="mx-auto max-w-xl p-6">
          <h1 className="text-lg font-bold">خوش آمدید — راه‌اندازی کامل شد</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            گفتگو با هوش سازمان در نسخه‌ی بعدی اسپرینت‌ها اضافه می‌شود.
          </p>
        </Surface>
      )}
    </AppShell>
  );
}