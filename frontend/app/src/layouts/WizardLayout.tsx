import { Outlet, useLocation } from "react-router-dom";
import Stepper from "../components/Stepper";

// The 7-step wizard routes are nested under this layout: it renders the shared
// page wrapper + step indicator, and the matched step renders into <Outlet />.
const STEP_BY_PATH: Record<string, number> = {
  "/": 0,
  "/owner": 1,
  "/otp": 2,
  "/workspace": 3,
  "/brain": 4,
  "/ingestion": 5,
  "/done": 6,
};

export default function WizardLayout() {
  const { pathname } = useLocation();
  const active = STEP_BY_PATH[pathname] ?? 0;
  return (
    <div style={{ maxWidth: 620, margin: "0 auto", padding: "40px 0" }}>
      <Stepper active={active} />
      <Outlet />
    </div>
  );
}
