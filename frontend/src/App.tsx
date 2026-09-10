import { useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { api, getToken } from "./api/client";
import Login from "./pages/Login";
import RegisterOrganization from "./pages/RegisterOrganization";
import OwnerAccount from "./pages/OwnerAccount";
import OtpVerify from "./pages/OtpVerify";
import Onboarding from "./pages/Onboarding";

interface Status {
  organization_status: string;
  next_step: string;
}

type Screen = "login" | "register" | "owner" | "otp" | "onboarding" | "chat";

// T-S1-9: bootstrap mockups wired to the API. Step selection follows the server
// (onboarding-status.next_step), not client-side guesses (C2 resume semantics).
export default function App() {
  const [screen, setScreen] = useState<Screen | null>(null);
  const [organizationId, setOrganizationId] = useState<string | null>(null);

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

  if (screen === "login") {
    return (
      <AppShell>
        <Login onDone={() => setScreen("onboarding")} />
        <p className="mx-auto mt-4 max-w-md text-center text-sm">
          حساب سازمان ندارید؟{" "}
          <button className="font-bold text-navy-600 underline" onClick={() => setScreen("register")}>
            ساخت سازمان جدید
          </button>
        </p>
      </AppShell>
    );
  }

  if (screen === "register") {
    return (
      <AppShell>
        <RegisterOrganization
          onCreated={(organizationId) => {
            setOrganizationId(organizationId);
            setScreen("owner");
          }}
          onBack={() => setScreen("login")}
        />
      </AppShell>
    );
  }

  if (screen === "owner") {
    return (
      <AppShell>
        <OwnerAccount
          organizationId={organizationId ?? ""}
          onDone={() => setScreen("otp")}
        />
      </AppShell>
    );
  }

  if (screen === "otp") {
    return (
      <AppShell>
        <OtpVerify onVerified={() => setScreen("onboarding")} />
      </AppShell>
    );
  }

  if (screen === "onboarding") {
    return (
      <AppShell>
        <Onboarding onStatus={(status) => { if (status.next_step === "chat") setScreen("chat"); }} />
      </AppShell>
    );
  }

  // «شروع گفتگو» — the Hive Mind chat itself lands with epic-09 (S3).
  return (
    <AppShell>
      <section className="mx-auto max-w-xl rounded-card border border-neutral-200 bg-neutral-0 p-6 shadow-card">
        <h1 className="text-lg font-bold">خوش آمدید — راه‌اندازی کامل شد</h1>
        <p className="mt-2 text-sm text-neutral-600">
          گفتگو با هوش سازمان در نسخه‌ی بعدی اسپرینت‌ها اضافه می‌شود.
        </p>
      </section>
    </AppShell>
  );
}
