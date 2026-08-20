import { useNavigate } from "react-router-dom";
import { useWizard } from "../hooks/use-wizard";
import RegisterOrganization from "../features/organization/components/RegisterOrganization";
import OwnerAccount from "../features/auth/components/OwnerAccount";
import OtpVerify from "../features/auth/components/OtpVerify";
import InitializeWorkspace from "../features/workspace/components/InitializeWorkspace";
import InitializeBrain from "../features/brain/components/InitializeBrain";
import IngestionFolder from "../features/ingestion/components/IngestionFolder";
import Done from "../features/onboarding/components/Done";

// Container components: wire the presentational feature pages to the router and
// the cross-step wizard store. The pages keep their (onDone/onBack/…) props so
// they stay router- and store-agnostic.

const STEP_PATHS = ["/", "/owner", "/otp", "/workspace", "/brain", "/ingestion", "/done"];

export function RegisterOrganizationRoute() {
  const navigate = useNavigate();
  const { setOrgName } = useWizard();
  return (
    <RegisterOrganization
      onDone={(org) => {
        setOrgName(org.name);
        navigate("/owner");
      }}
    />
  );
}

export function OwnerAccountRoute() {
  const navigate = useNavigate();
  const { state, setPhone } = useWizard();
  return (
    <OwnerAccount
      initialPhone={state.phone}
      onDone={(r) => {
        setPhone(r.phone);
        navigate("/otp");
      }}
      onBack={() => navigate("/")}
    />
  );
}

export function OtpVerifyRoute() {
  const navigate = useNavigate();
  const { state } = useWizard();
  return (
    <OtpVerify
      phone={state.phone ?? ""}
      onDone={() => navigate("/workspace")}
      onBack={() => navigate("/owner")}
    />
  );
}

export function InitializeWorkspaceRoute() {
  const navigate = useNavigate();
  return (
    <InitializeWorkspace onDone={() => navigate("/brain")} onBack={() => navigate("/otp")} />
  );
}

export function InitializeBrainRoute() {
  const navigate = useNavigate();
  return (
    <InitializeBrain onDone={() => navigate("/ingestion")} onBack={() => navigate("/workspace")} />
  );
}

export function IngestionFolderRoute() {
  const navigate = useNavigate();
  const { setDocuments } = useWizard();
  return (
    <IngestionFolder
      onDone={(r) => {
        setDocuments(r.documents);
        navigate("/done");
      }}
      onBack={() => navigate("/brain")}
    />
  );
}

export function DoneRoute() {
  const navigate = useNavigate();
  const { state } = useWizard();
  const jump = (step: number) => navigate(STEP_PATHS[step] ?? "/");
  return <Done orgName={state.orgName} documents={state.documents} onJump={jump} />;
}
