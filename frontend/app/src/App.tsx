import { useState } from "react";
import type { Organization } from "./api";
import RegisterOrganization from "./pages/RegisterOrganization";

export interface WizardState {
  orgId?: string;
  orgName?: string;
  workspaceId?: string;
  userId?: string;
}

export default function App() {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>({});

  const onOrgCreated = (org: Organization) => {
    setState((s) => ({ ...s, orgId: org.id, orgName: org.displayName, workspaceId: org.workspaceId }));
    setStep(1);
  };

  if (step === 0) return <RegisterOrganization onDone={onOrgCreated} />;
  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0", textAlign: "center" }}>
      <h2>سازمان «{state.orgName}» ساخته شد ✅</h2>
      <div className="card">
        <p style={{ color: "var(--muted)" }}>گام‌های بعدی (مدیر سازمان، تأیید کد، فضای کار، هوش سازمان، اسناد) در ادامه پیاده‌سازی می‌شوند. عملیات موفق به Backend متصل شد ({state.orgId}).</p>
      </div>
    </div>
  );
}
