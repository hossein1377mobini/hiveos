// Domain types shared across the feature services and the wizard UI.
// Extracted from the former monolithic api.ts (S1-14 structural refactor).

export type OnboardingStatus = "pending" | "in_progress" | "completed";
export type DocumentStatus = "detected" | "processing" | "ready" | "failed";

export interface OrganizationCreate {
  displayName: string;
  industry: string;
  companySize: string;
  businessDescription: { whatYouDo: string; productsServices: string };
  aiModel: { provider: string; apiKey: string };
}
export interface Organization {
  id: string;
  name: string;
  status: string;
  tenantId: string;
  workspaceId: string;
  createdAt: string;
}
export interface OwnerCreate {
  phone: string;
  password: string;
  confirmPassword: string;
}
export interface OtpSendRequest {
  phone: string;
}
export interface OtpVerifyRequest {
  phone: string;
  code: string;
}

export interface WorkspaceSettings {
  language: string;
  timeZone: string;
  dateFormat: string;
  numberFormat: string;
  defaultLocale: string;
}
export interface WorkspaceInitResult {
  workspaceId: string;
  status: string;
  settings: WorkspaceSettings;
}
export interface BrainInitResult {
  brainId: string;
  knowledgeRepositoryId: string;
  vectorIndexId: string;
  status: string;
  rag: { embeddingProvider: string; defaultLanguage: string };
}
export interface IngestionCounts {
  detected: number;
  processing: number;
  ready: number;
  failed: number;
}
export interface IngestionConfigureResult {
  active: boolean;
  folderPath: string;
  watchStartedAt?: string;
  counts: IngestionCounts;
}
export interface IngestionStatusResult {
  active: boolean;
  folderPath?: string;
  counts: IngestionCounts;
}
export interface DocumentItem {
  id: string;
  filename: string;
  format: string;
  status: DocumentStatus;
  error?: string;
}
// S1-18 paginated-list envelope: GET /documents returns {items, meta} instead of
// a bare array (see docs/decisions/2026-08-20-paginated-list-envelope.md).
export interface PageMeta {
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}
export interface DocumentPage {
  items: DocumentItem[];
  meta: PageMeta;
}
export interface OnboardingStatusResult {
  onboardingStatus: OnboardingStatus;
  missingSteps?: string[];
}
export interface CompleteOnboardingResult {
  onboardingStatus: OnboardingStatus;
  next?: string;
}
