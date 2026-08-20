import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { DocumentItem } from "../types";

// Cross-step feature state shared by the 7-step onboarding wizard (S1-14).
// Replaces the former App.tsx `step` state-machine: the *position* now lives in
// the URL (react-router) while the *data* collected so far lives here.

export interface WizardState {
  orgName?: string;
  phone?: string;
  documents?: DocumentItem[];
}

interface WizardContextValue {
  state: WizardState;
  setOrgName: (name: string) => void;
  setPhone: (phone: string) => void;
  setDocuments: (documents: DocumentItem[]) => void;
}

const WizardContext = createContext<WizardContextValue | null>(null);

export function WizardProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WizardState>({});

  const setOrgName = useCallback((orgName: string) => setState((s) => ({ ...s, orgName })), []);
  const setPhone = useCallback((phone: string) => setState((s) => ({ ...s, phone })), []);
  const setDocuments = useCallback(
    (documents: DocumentItem[]) => setState((s) => ({ ...s, documents })),
    [],
  );

  const value = useMemo(
    () => ({ state, setOrgName, setPhone, setDocuments }),
    [state, setOrgName, setPhone, setDocuments],
  );

  return <WizardContext.Provider value={value}>{children}</WizardContext.Provider>;
}

export function useWizard(): WizardContextValue {
  const ctx = useContext(WizardContext);
  if (!ctx) throw new Error("useWizard must be used within a WizardProvider");
  return ctx;
}
