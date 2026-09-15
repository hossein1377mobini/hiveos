// API client (ADR-023 thin client): single origin via the /api proxy, envelope
// handling in one place. Errors become ApiError whose `message` is ALREADY the
// Persian sentence the UI shows (see api/errors.ts) - pages never render the
// server's English developer message.
import { persianError } from "./errors";

export const API_BASE = "/api/v1";
// F: without a ceiling a hung proxy/backend left the UI on "…" forever.
const REQUEST_TIMEOUT_MS = 90_000;

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

interface Envelope {
  success: boolean;
  data?: unknown;
  message?: string | null;
  error?: { code: string; message: string };
}

export function getToken(): string | null {
  return localStorage.getItem("hiveos.session");
}

export function setToken(token: string): void {
  localStorage.setItem("hiveos.session", token);
}

export function clearToken(): void {
  localStorage.removeItem("hiveos.session");
}

export async function api<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE" | "PUT", // S13 (external review)
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // D6: multipart uploads must set their own boundary - and going through this
  // client (instead of a raw fetch) is what keeps 401 -> login redirect and the
  // server's error envelope working for uploads too.
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json"; // S13

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === "AbortError";
    const code = aborted ? "CLIENT_TIMEOUT" : "CLIENT_OFFLINE";
    throw new ApiError(0, code, persianError(code));
  } finally {
    clearTimeout(timer);
  }

  let payload: Envelope;
  try {
    payload = (await response.json()) as Envelope;
  } catch {
    // P0-1/P0-2: an error page instead of an envelope means a PROXY answered,
    // not the API. nginx sends HTML for 413 (and 502/504) with
    // `client_max_body_size`, so the HTTP status is the only thing that still
    // names the real cause. Discarding it here is what turned "the file is over
    // the size limit" into the unreadable "پاسخ سرور قابل خواندن نبود".
    if (!response.ok) {
      throw new ApiError(
        response.status,
        "HTTP_" + response.status,
        persianError("HTTP_" + response.status, response.status),
      );
    }
    // 2xx with a body that is not the envelope: the API did answer, so this is
    // the old bad-response case and the status carries no extra meaning.
    throw new ApiError(
      response.status,
      "CLIENT_BAD_RESPONSE",
      persianError("CLIENT_BAD_RESPONSE", response.status),
    );
  }

  if (!response.ok || !payload.success) {
    const error = payload.error ?? { code: "UNKNOWN", message: "" };
    // S13 (external review): an expired/revoked session ends at the login screen.
    //
    // The redirect must not fire inside the admin panel: that surface has its
    // own login and its own token, and an anonymous visitor to /admin is not a
    // signed-out organization user. Bouncing them to /login made the panel
    // unreachable by URL - the operator could never even see its login form,
    // because the identity probe the shell fires on every route answered 401
    // and this line sent the browser away. Purely client-side: a real
    // organization 401 outside /admin still lands on /login.
    const path = window.location.pathname;
    // Two surfaces must never be bounced to /login:
    //  - the admin panel, which has its own login and its own token;
    //  - the public signup screens (login/register/owner), where nobody is
    //    signed in by definition and a stray probe must not eject the user
    //    mid-flow.
    const redirectable =
      path !== "/login" &&
      path !== "/register" &&
      path !== "/owner" &&
      path !== "/admin" &&
      !path.startsWith("/admin/");
    if (
      response.status === 401 &&
      ["AUTH_REQUIRED", "SESSION_EXPIRED", "SESSION_REVOKED"].includes(error.code)
    ) {
      clearToken();
      if (redirectable) window.location.assign("/login");
    }
    throw new ApiError(
      response.status,
      error.code,
      persianError(error.code, response.status, error.message),
    );
  }
  return payload.data as T;
}
