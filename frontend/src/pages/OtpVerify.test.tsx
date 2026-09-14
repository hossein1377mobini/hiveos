import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import OtpVerify from "./OtpVerify";
import { renderWithRouter } from "../test/render";

/**
 * OTP entry. The page auto-submits when the last box is filled, so the tests
 * check that the code is sent exactly once — a double submit here would burn one
 * of the few allowed attempts (the server locks after too many).
 */

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A fetch stub that answers send-otp, then whatever the verify handler returns. */
function stubAuth(verifyResult: { ok: boolean; status?: number }) {
  return vi.fn(async (url: string) => {
    if (String(url).includes("send-otp") || String(url).includes("resend-otp")) {
      return respond({ success: true, data: { dev_code: "1234" } });
    }
    if (verifyResult.ok) return respond({ success: true, data: {} });
    return respond(
      { success: false, error: { code: "OTP_INVALID", message: "bad code" } },
      verifyResult.status ?? 400,
    );
  });
}

function boxes() {
  return screen.getAllByRole("textbox");
}

function typeCode(code: string) {
  const inputs = boxes();
  code.split("").forEach((digit, index) => {
    fireEvent.change(inputs[index], { target: { value: digit } });
  });
}

describe("OtpVerify", () => {
  it("sends the code once on mount", async () => {
    const fetchMock = stubAuth({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OtpVerify onVerified={() => {}} />, { route: "/otp" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const sends = fetchMock.mock.calls.filter(([url]) => String(url).includes("send-otp"));
    expect(sends).toHaveLength(1);
  });

  it("auto-submits when the last digit is entered, and only once", async () => {
    const onVerified = vi.fn();
    const fetchMock = stubAuth({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    renderWithRouter(<OtpVerify onVerified={onVerified} />, { route: "/otp" });

    await screen.findByTestId("dev-code");
    typeCode("1234");

    await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
    const verifies = fetchMock.mock.calls.filter(([url]) => String(url).includes("verify-otp"));
    // One attempt, not two: the server counts each call.
    expect(verifies).toHaveLength(1);
    const [, init] = verifies[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ code: "1234" });
  });

  it("announces a rejected code and clears the boxes for another try", async () => {
    const onVerified = vi.fn();
    vi.stubGlobal("fetch", stubAuth({ ok: false }));
    renderWithRouter(<OtpVerify onVerified={onVerified} />, { route: "/otp" });

    await screen.findByTestId("dev-code");
    typeCode("9999");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("کد تأیید درست نیست");
    expect(onVerified).not.toHaveBeenCalled();
    // Every box is empty again, so the next attempt starts from zero.
    boxes().forEach((box) => expect(box).toHaveValue(""));
  });

  it("accepts Persian digits", async () => {
    // The number pad on a Persian keyboard produces ۰-۹, and the fields are
    // numeric: a value the user can type but the form ignores is a dead end.
    const onVerified = vi.fn();
    vi.stubGlobal("fetch", stubAuth({ ok: true }));
    renderWithRouter(<OtpVerify onVerified={onVerified} />, { route: "/otp" });

    await screen.findByTestId("dev-code");
    typeCode("۱۲۳۴");

    await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
  });

  it("labels each box for a screen reader, in Persian digits", async () => {
    vi.stubGlobal("fetch", stubAuth({ ok: true }));
    renderWithRouter(<OtpVerify onVerified={() => {}} />, { route: "/otp" });

    await screen.findByTestId("dev-code");
    expect(screen.getByLabelText("رقم ۱")).toBeInTheDocument();
    expect(screen.getByLabelText("رقم ۴")).toBeInTheDocument();
  });
});
