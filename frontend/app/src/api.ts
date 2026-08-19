// Typed API client for the HiveOS onboarding backend (v1).
// Same-origin calls go through the Vite dev-server proxy (/api -> :8100) so the
// onb...ding/session cookies set by US-001/US-002 are stored on the SPA origin
// and sent automatically (HttpOnly cookies still flow over the proxy).

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  details?: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin", // always carry onb...ding/session cookies
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const msg = (json as { message?: string } | null)?.message ?? `${method} ${path} failed (${res.status})`;
    throw new ApiError(res.status, msg, json ?? undefined);
  }
  return json as T;
}

export interface OrganizationCreate {
  displayName: string;
  industry: string;
  companySize: string;
  businessDescription: { whatYouDo: string; productsServices: string };
  aiModel: { provider: string; apiKey: string };
}
export interface Organization {
  id: string;
  displayName: string;
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
  status: string;
  error?: string;
}
export interface OnboardingStatusResult {
  onboardingStatus: string;
  missingSteps?: string[];
}
export interface CompleteOnboardingResult {
  onboardingStatus: string;
  next?: string;
}

export const api = {
  createOrganization: (p: OrganizationCreate) => request<Organization>("POST", "/organizations", p),
  createOwner: (p: OwnerCreate) => request<{ userId: string; organizationId: string; status: string; sessionIssued: boolean }>("POST", "/users/owner", p),
  sendOtp: (p: OtpSendRequest) => request<{ status: string; resendAfterSeconds: number; expiresInSeconds: number }>("POST", "/auth/send-otp", p),
  verifyOtp: (p: OtpVerifyRequest) => request<{ verified: boolean; userStatus: string; organizationStatus: string }>("POST", "/auth/verify-otp", p),
  initializeWorkspace: () => request<WorkspaceInitResult>("POST", "/workspaces/initialize"),
  initializeBrain: () => request<BrainInitResult>("POST", "/brain/initialize"),
  configureIngestion: (folderPath: string) =>
    request<IngestionConfigureResult>("POST", "/ingestion-folder/configure", { folderPath }),
  getIngestionStatus: () => request<IngestionStatusResult>("GET", "/ingestion-folder/status"),
  listDocuments: () => request<DocumentItem[]>("GET", "/documents"),
  getOnboardingStatus: () => request<OnboardingStatusResult>("GET", "/onboarding/status"),
  completeOnboarding: () => request<CompleteOnboardingResult>("POST", "/onboarding/complete"),
};
