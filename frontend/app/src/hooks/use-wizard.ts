// Convenience re-export: the wizard hook is co-located with its context/store
// (React convention), surfaced here so feature code imports it from `hooks/`.
export { useWizard } from "../stores/wizard-store";
export type { WizardState } from "../stores/wizard-store";
