import { useEffect, useState } from "react";
import { AppShell, type NavId } from "./components/AppShell";
import { api, getToken } from "./api/client";
import Login from "./pages/Login";
import RegisterOrganization from "./pages/RegisterOrganization";
import OwnerAccount from "./pages/OwnerAccount";
import OtpVerify from "./pages/OtpVerify";
import Onboarding from "./pages/Onboarding";
import Wallet from "./pages/Wallet";
import Chat from "./pages/Chat";
import AdminApp from "./admin/AdminApp";

interface Status {
  organization_status: string;
  next_step: string;
}

type Screen = "login" | "register" | "owner" | "otp" | "onboarding" | "chat" | "wallet";

// T-S1-9: bootstrap mockups wired to the API. Step selection follows the server
// (onboarding-status.next_step), not client-side guesses (C2 resume semantics).
export default function App() {
  const [screen, setScreen] = useState<Screen | null>(null);
  const [organizationId, setOrganizationId] = useState<string | null>(null);

  // Admin panel rides the same SPA under /admin (epic-16).
  if (window.location.pathname.startsWith("/admin")) {
    return <AdminApp />;
  }

  useEffect(() => {
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
  }, []);

  function routeFromStatus(nextStep: string) {
    if (nextStep === "owner") setScreen("owner");
    else if (nextStep === "expired") setScreen("onboarding");
    else if (nextStep === "workspace" || nextStep === "brain" || nextStep === "knowledge_source")
      setScreen("onboarding");
    else if (nextStep === "chat") setScreen("chat");
    else setScreen("login");
  }

  if (screen === null) {
    return <AppShell><p className="p-6 text-sm text-neutral-600">در حال بارگذاری…</p></AppShell>;
  }

  // Auth screens (00-03 mockups) are standalone pages WITHOUT the app shell —
  // the shell (10-app-shell.html) only appears after onboarding completes.
  if (screen === "login" || screen === "register" || screen === "owner" || screen === "otp") {
    return (
      <div className="flex min-h-screen items-start justify-center px-4 pb-16 pt-11">
        <div className="w-full max-w-[700px]">
          {screen === "login" && (
            <>
              <Login onDone={() => setScreen("onboarding")} />
              <p className="mx-auto mt-3 max-w-md text-center text-[13px] text-neutral-600">
                حساب سازمان ندارید؟{" "}
                <button className="font-bold text-navy-600 no-underline hover:underline" onClick={() => setScreen("register")}>
                  ساخت سازمان جدید
                </button>
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
            <OwnerAccount organizationId={organizationId ?? ""} onDone={() => setScreen("otp")} />
          )}
          {screen === "otp" && <OtpVerify onVerified={() => setScreen("onboarding")} />}
        </div>
      </div>
    );
  }

  if (screen === "onboarding") {
    return (
      <AppShell>
        <Onboarding onStatus={(status) => { if (status.next_step === "chat") setScreen("chat"); }} />
      </AppShell>
    );
  }

  return (
    <AppShell
      active={screen as NavId}
      onNavigate={(id: NavId) => setScreen(id === "wallet" ? "wallet" : "chat")}
    >
      {screen === "wallet" ? (
        <Wallet />
      ) : screen === "chat" ? (
        <Chat />
      ) : (
        <section className="mx-auto max-w-xl rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
          <h1 className="text-lg font-bold">خوش آمدید — راه‌اندازی کامل شد</h1>
          <p className="mt-2 text-sm text-neutral-600">
            گفتگو با هوش سازمان در نسخه‌ی بعدی اسپرینت‌ها اضافه می‌شود.
          </p>
        </section>
      )}
    </AppShell>
  );
}
