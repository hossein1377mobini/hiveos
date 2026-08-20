import { Navigate, Route, Routes } from "react-router-dom";
import { WizardProvider } from "../stores/wizard-store";
import WizardLayout from "../layouts/WizardLayout";
import {
  DoneRoute,
  IngestionFolderRoute,
  InitializeBrainRoute,
  InitializeWorkspaceRoute,
  OtpVerifyRoute,
  OwnerAccountRoute,
  RegisterOrganizationRoute,
} from "./routes";

export default function App() {
  return (
    <WizardProvider>
      <Routes>
        <Route element={<WizardLayout />}>
          <Route path="/" element={<RegisterOrganizationRoute />} />
          <Route path="/owner" element={<OwnerAccountRoute />} />
          <Route path="/otp" element={<OtpVerifyRoute />} />
          <Route path="/workspace" element={<InitializeWorkspaceRoute />} />
          <Route path="/brain" element={<InitializeBrainRoute />} />
          <Route path="/ingestion" element={<IngestionFolderRoute />} />
          <Route path="/done" element={<DoneRoute />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </WizardProvider>
  );
}
