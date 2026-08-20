import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, describeError } from "./http";
import { organizationApi } from "./organizationApi";
import { authApi } from "./authApi";
import { onboardingApi } from "./onboardingApi";

function jsonResponse(body: unknown, status: number) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  };
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api request()", () => {
  it("returns parsed JSON on 2xx and POSTs the serialized body", async () => {
    const payload = {
      displayName: "شرکت آریا",
      industry: "فناوری اطلاعات",
      companySize: "10_to_49",
      businessDescription: { whatYouDo: "1234567890", productsServices: "1234567890" },
      aiModel: { provider: "DeepSeek", apiKey: "sk-test" },
    };
    fetchMock.mockResolvedValue(jsonResponse({ id: "o1", status: "pending" }, 201));

    const res = await organizationApi.createOrganization(payload);

    expect(res).toEqual({ id: "o1", status: "pending" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, { method: string; body: string }];
    expect(url).toBe("/api/v1/organizations");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(payload);
  });

  it("returns parsed JSON on a 2xx GET", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ onboardingStatus: "in_progress", missingSteps: ["owner"] }, 200),
    );
    const res = await onboardingApi.getOnboardingStatus();
    expect(res).toEqual({ onboardingStatus: "in_progress", missingSteps: ["owner"] });
  });

  it("returns undefined for a 204", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204, text: async () => "" });
    await expect(onboardingApi.completeOnboarding()).resolves.toBeUndefined();
  });

  it("throws ApiError{status, error, message} on a non-2xx", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: "PHONE_TAKEN", message: "this phone already exists" }, 409),
    );
    const err = await authApi
      .createOwner({ phone: "+989123456789", password: "x", confirmPassword: "x" })
      .catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.error).toBe("PHONE_TAKEN");
    expect(err.message).toBe("this phone already exists");
  });

  it("falls back to error 'unknown' on a malformed error body", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => "<html>boom</html>" });
    const err = await onboardingApi.getOnboardingStatus().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.error).toBe("unknown");
  });
});

describe("describeError", () => {
  const generic = "خطای عمومی";

  it("maps 401 to the session-expired message", () => {
    expect(describeError(new ApiError(401, "UNAUTH", "raw"), generic)).toBe(
      "نشست شما منقضی شده است. برای ادامه دوباره وارد شوید.",
    );
  });

  it("maps 403 and 404 to the same not-available message", () => {
    const msg = "این محتوا در دسترس نیست.";
    expect(describeError(new ApiError(403, "FORBIDDEN", "raw"), generic)).toBe(msg);
    expect(describeError(new ApiError(404, "NOT_FOUND", "raw"), generic)).toBe(msg);
  });

  it("maps 409 to the default conflict message or the page-specific override", () => {
    expect(describeError(new ApiError(409, "CONFLICT", "raw"), generic)).toContain("تعارض دارد");
    expect(
      describeError(new ApiError(409, "CONFLICT", "raw"), generic, "این شماره پیش‌تر ثبت شده است."),
    ).toContain("ثبت شده است");
  });

  it("maps 410 to the expired-code message", () => {
    expect(describeError(new ApiError(410, "OTP_EXPIRED", "raw"), generic)).toBe(
      "کد منقضی شده است. کد تازه دریافت کنید.",
    );
  });

  it("maps 429 to the rate-limit message", () => {
    expect(describeError(new ApiError(429, "RATE_LIMIT", "raw"), generic)).toContain("زیاد شده است");
  });

  it("returns the generic fallback for unknown statuses and non-ApiError values", () => {
    expect(describeError(new ApiError(500, "INTERNAL", "raw"), generic)).toBe(generic);
    expect(describeError(new ApiError(418, "TEAPOT", "raw"), generic)).toBe(generic);
    expect(describeError(new Error("network down"), generic)).toBe(generic);
    expect(describeError("just a string", generic)).toBe(generic);
  });

  it("never surfaces a raw server message", () => {
    const raw = "SQLSTATE 23505 secret internal detail";
    const out = describeError(new ApiError(409, "CONFLICT", raw), generic);
    expect(out).not.toContain("SQLSTATE");
    expect(out).not.toContain("secret");
  });
});
