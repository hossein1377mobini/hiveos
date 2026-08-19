import { useState } from "react";
import type { Organization, DocumentItem } from "./api";
import RegisterOrganization from "./pages/RegisterOrganization";
import OwnerAccount from "./pages/OwnerAccount";
import OtpVerify from "./pages/OtpVerify";
import InitializeWorkspace from "./pages/InitializeWorkspace";
import InitializeBrain from "./pages/InitializeBrain";
import IngestionFolder from "./pages/IngestionFolder";
import Done from "./pages/Done";

export interface WizardState {
  orgId?: string;
  orgName?: string;
  workspaceId?: string;
  brainId?: string;
  userId?: string;
  phone?: string;
  folderPath?: string;
  documents?: DocumentItem[];
  onboardingStatus?: string;
}

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

  const onWorkspaceDone = (r: { workspaceId: string }) => {
    setState((s) => ({ ...s, workspaceId: r.workspaceId }));
    setStep(4);
  };

  const onBrainDone = (r: { brainId: string }) => {
    setState((s) => ({ ...s, brainId: r.brainId }));
    setStep(5);
  };

  const onIngestionDone = (r: { folderPath: string; documents: DocumentItem[] }) => {
    setState((s) => ({ ...s, folderPath: r.folderPath, documents: r.documents }));
    setStep(6);
  };

  const jump = (s: number) => setStep(s);

  if (step === 0) return <RegisterOrganization onDone={onOrgCreated} />;
  if (step === 1) return <OwnerAccount onDone={onOwnerCreated} onBack={() => setStep(0)} />;
  if (step === 2) return <OtpVerify phone={state.phone ?? ""} onDone={onVerified} onBack={() => setStep(1)} />;
  if (step === 3) return <InitializeWorkspace onDone={onWorkspaceDone} onBack={() => setStep(2)} />;
  if (step === 4) return <InitializeBrain onDone={onBrainDone} onBack={() => setStep(3)} />;
  if (step === 5) return <IngestionFolder onDone={onIngestionDone} onBack={() => setStep(4)} />;
  return <Done orgName={state.orgName} documents={state.documents} onJump={jump} />;
}
