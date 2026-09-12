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
    // a proxy error page (HTML) or a truncated body - never a raw stack string
    throw new ApiError(
      response.status,
      "CLIENT_BAD_RESPONSE",
      persianError("CLIENT_BAD_RESPONSE", response.status),
    );
  }

  if (!response.ok || !payload.success) {
    const error = payload.error ?? { code: "UNKNOWN", message: "" };
    // S13 (external review): an expired/revoked session ends at the login screen.
    if (
      response.status === 401 &&
      ["AUTH_REQUIRED", "SESSION_EXPIRED", "SESSION_REVOKED"].includes(error.code)
    ) {
      clearToken();
      if (window.location.pathname !== "/login") window.location.assign("/login");
    }
    throw new ApiError(
      response.status,
      error.code,
      persianError(error.code, response.status, error.message),
    );
  }
  return payload.data as T;
}
