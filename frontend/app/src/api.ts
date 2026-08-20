// Typed API client for the HiveOS onboarding backend (v1).
// Same-origin calls go through the Vite dev-server proxy (/api -> :8100) so the
// onboarding/session cookies set by US-001/US-002 are stored on the SPA origin
// and sent automatically (HttpOnly cookies still flow over the proxy).

const BASE = "/api/v1";

// --- Envelope + error types -------------------------------------------------

// Consistent, typed error envelope surfaced to the UI. `error` is the stable
// machine key returned by the backend (OpenAPI `Error.error`); `message` is the
// server's human-readable text and is NEVER rendered directly to users (always
// mapped through describeError).
export interface ApiErrorBody {
  status: number;
  error: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  error: string;
  details?: unknown;
  constructor(status: number, error: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.error = error;
    this.details = details;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin", // always carry onboarding/session cookies
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
    const body = (json as Partial<ApiErrorBody> | null) ?? {};
    const message = body.message ?? `${method} ${path} failed (${res.status})`;
    throw new ApiError(res.status, body.error ?? "unknown", message, json ?? undefined);
  }
  return json as T;
}

// --- Curated Persian error mapping ------------------------------------------
// Central place that maps every HTTP/network failure to a known, curated
// Persian message. Raw server messages (e.message / response bytes) are never
// surfaced to the user. `generic` is the page-specific fallback for unknown
// statuses and non-API errors; `conflict` overrides the 409 message per page.

export function describeError(e: unknown, generic: string, conflict?: string): string {
  if (!(e instanceof ApiError)) return generic;
  switch (e.status) {
    case 401:
      return "نشست شما منقضی شده است. برای ادامه دوباره وارد شوید.";
    case 403:
    case 404:
      return "این محتوا در دسترس نیست.";
    case 409:
      return conflict ?? "داده‌های واردشده با وضعیت فعلی تعارض دارد.";
    case 410:
      return "کد منقضی شده است. کد تازه دریافت کنید.";
    case 429:
      return "درخواست‌ها زیاد شده است؛ کمی صبر کنید و دوباره تلاش کنید.";
    default:
      return generic;
  }
}

// --- Domain types -----------------------------------------------------------

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

export const api = {
  createOrganization: (p: OrganizationCreate) => request<Organization>("POST", "/organizations", p),
  createOwner: (p: OwnerCreate) => request<{ userId: string; organizationId: string; status: string; sessionIssued: boolean }>("POST", "/users/owner", p),
  sendOtp: (p: OtpSendRequest) => request<{ status: string; resendAfterSeconds: number; expiresInSeconds: number }>("POST", "/auth/send-otp", p),
  resendOtp: (p: OtpSendRequest) => request<{ status: string; resendAfterSeconds: number; expiresInSeconds: number }>("POST", "/auth/resend-otp", p),
  verifyOtp: (p: OtpVerifyRequest) => request<{ verified: boolean; userStatus: string; organizationStatus: string }>("POST", "/auth/verify-otp", p),
  initializeWorkspace: () => request<WorkspaceInitResult>("POST", "/workspaces/initialize"),
  initializeBrain: () => request<BrainInitResult>("POST", "/brain/initialize"),
  configureIngestion: (folderPath: string) =>
    request<IngestionConfigureResult>("POST", "/ingestion-folder/configure", { folderPath }),
  getIngestionStatus: () => request<IngestionStatusResult>("GET", "/ingestion-folder/status"),
  listDocuments: () => request<DocumentPage>("GET", "/documents"),
  getOnboardingStatus: () => request<OnboardingStatusResult>("GET", "/onboarding/status"),
  completeOnboarding: () => request<CompleteOnboardingResult>("POST", "/onboarding/complete"),
};
