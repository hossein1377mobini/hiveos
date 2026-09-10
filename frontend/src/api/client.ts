// API client (ADR-023 thin client): single origin via the /api proxy, envelope
// handling in one place. Errors become ApiError with the server code/message.
export const API_BASE = "/api/v1";

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
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let payload: Envelope;
  try {
    payload = (await response.json()) as Envelope;
  } catch {
    throw new ApiError(response.status, "CLIENT_BAD_RESPONSE", "پاسخ سرور قابل خواندن نیست.");
  }

  if (!response.ok || !payload.success) {
    const error = payload.error ?? { code: "UNKNOWN", message: "خطای ناشناخته." };
    throw new ApiError(response.status, error.code, error.message);
  }
  return payload.data as T;
}
