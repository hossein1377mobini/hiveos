// Shared HTTP plumbing for every feature service (S1-14 structural refactor).
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

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
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
    const errBody = (json as Partial<ApiErrorBody> | null) ?? {};
    const message = errBody.message ?? `${method} ${path} failed (${res.status})`;
    throw new ApiError(res.status, errBody.error ?? "unknown", message, json ?? undefined);
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
