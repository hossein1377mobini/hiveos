import { useState } from "react";
import type { Organization } from "./api";
import RegisterOrganization from "./pages/RegisterOrganization";
import OwnerAccount from "./pages/OwnerAccount";
import OtpVerify from "./pages/OtpVerify";

export interface WizardState {
  orgId?: string;
  orgName?: string;
  workspaceId?: string;
  userId?: string;
  phone?: string;
}

const LATER_STEPS = ["فضای کار", "هوش سازمان", "اسناد"];

export default function App() {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>({});

  const onOrgCreated = (org: Organization) => {
    setState((s) => ({ ...s, orgId: org.id, orgName: org.displayName, workspaceId: org.workspaceId }));
    setStep(1);
  };

  const onOwnerCreated = (r: { userId: string; phone: string }) => {
    setState((s) => ({ ...s, userId: r.userId, phone: r.phone }));
    setStep(2);
  };

  const onVerified = () => setStep(3);

  if (step === 0) return <RegisterOrganization onDone={onOrgCreated} />;
  if (step === 1) return <OwnerAccount onDone={onOwnerCreated} onBack={() => setStep(0)} />;
  if (step === 2) return <OtpVerify phone={state.phone ?? ""} onDone={onVerified} onBack={() => setStep(1)} />;

  // Steps 3–5 (فضای کار / هوش سازمان / اسناد) — placeholders so the app still compiles/serves.
  const label = LATER_STEPS[step - 3] ?? "";
  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <div className="card" style={{ textAlign: "center" }}>
        <h2 style={{ marginTop: 0 }}>«{label}»</h2>
        <p style={{ color: "var(--muted)" }}>این مرحله به‌زودی</p>
      </div>
    </div>
  );
}
