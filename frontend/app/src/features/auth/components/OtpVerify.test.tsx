import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authApi } from "../../../services/authApi";
import { ApiError } from "../../../services/http";
import OtpVerify from "./OtpVerify";
import { fillOtp, PHONE } from "../../../test/helpers";

vi.mock("../../../services/authApi", () => ({
  authApi: { createOwner: vi.fn(), sendOtp: vi.fn(), resendOtp: vi.fn(), verifyOtp: vi.fn() },
}));

const sendOtp = () => vi.mocked(authApi.sendOtp);
const resendOtp = () => vi.mocked(authApi.resendOtp);
const verifyOtp = () => vi.mocked(authApi.verifyOtp);

function renderForm() {
  const onDone = vi.fn();
  const onBack = vi.fn();
  render(<OtpVerify phone={PHONE} onDone={onDone} onBack={onBack} />);
  return { onDone, onBack };
}

describe("OtpVerify", () => {
  beforeEach(() => {
    sendOtp().mockReset();
    resendOtp().mockReset();
    verifyOtp().mockReset();
    sendOtp().mockResolvedValue({ status: "sent", resendAfterSeconds: 30, expiresInSeconds: 120 });
    resendOtp().mockResolvedValue({ status: "sent", resendAfterSeconds: 30, expiresInSeconds: 120 });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("renders 6 digit boxes and typing advances focus to the next box", async () => {
    renderForm();
    await waitFor(() => expect(sendOtp()).toHaveBeenCalledTimes(1));
    const boxes = screen.getAllByRole("textbox");
    expect(boxes).toHaveLength(6);

    fireEvent.change(boxes[0], { target: { value: "5" } });
    expect(boxes[1]).toHaveFocus();
  });

  it("submits the 6-digit code to verifyOtp with the same phone passed in", async () => {
    const user = userEvent.setup();
    const { onDone } = renderForm();
    verifyOtp().mockResolvedValue({ verified: true, userStatus: "active", organizationStatus: "active" });
    await waitFor(() => expect(sendOtp()).toHaveBeenCalledTimes(1));

    fillOtp("123456");
    await user.click(screen.getByRole("button", { name: "تأیید" }));

    await waitFor(() =>
      expect(verifyOtp()).toHaveBeenCalledWith({ phone: PHONE, code: "123456" }),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
  });

  it("clears inputs and re-focuses box 1 with the curated error on a 400 response", async () => {
    const user = userEvent.setup();
    renderForm();
    verifyOtp().mockRejectedValue(new ApiError(400, "INVALID_CODE", "raw server detail"));
    await waitFor(() => expect(sendOtp()).toHaveBeenCalledTimes(1));

    fillOtp("000000");
    await user.click(screen.getByRole("button", { name: "تأیید" }));

    expect(await screen.findByText("کد واردشده درست نیست.")).toBeInTheDocument();
    const boxes = screen.getAllByRole("textbox");
    boxes.forEach((b) => expect(b).toHaveValue(""));
    expect(boxes[0]).toHaveFocus();
  });

  it("keeps the resend cooldown independent of OTP expiry and re-calls resendOtp", async () => {
    vi.useFakeTimers();
    sendOtp().mockResolvedValue({ status: "sent", resendAfterSeconds: 5, expiresInSeconds: 120 });
    renderForm();

    await act(async () => {}); // flush the initial async send
    expect(sendOtp()).toHaveBeenCalledTimes(1);
    // cooldown active: resend button is disabled and shows the countdown
    expect(screen.getByText(/ارسال مجدد تا/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    // resend is now enabled while the OTP has NOT yet expired (independent)
    expect(screen.getByRole("button", { name: "ارسال مجدد کد" })).toBeEnabled();
    expect(screen.queryByText("کد منقضی شده است.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "ارسال مجدد کد" }));
    await act(async () => {});
    expect(sendOtp()).toHaveBeenCalledTimes(1); // initial send untouched
    expect(resendOtp()).toHaveBeenCalledTimes(1); // resend goes to the dedicated endpoint
  });

  it("renders the expired-code message on a 410 response", async () => {
    const user = userEvent.setup();
    renderForm();
    verifyOtp().mockRejectedValue(new ApiError(410, "OTP_EXPIRED", "raw server detail"));
    await waitFor(() => expect(sendOtp()).toHaveBeenCalledTimes(1));

    fillOtp("111111");
    await user.click(screen.getByRole("button", { name: "تأیید" }));

    expect(
      await screen.findByText("کد منقضی شده است. کد تازه دریافت کنید."),
    ).toBeInTheDocument();
  });

  it("keeps the resend button disabled for the cooldown carried by a 429 body", async () => {
    vi.useFakeTimers();
    // S1-19: the backend now surfaces ``resendAfterSeconds`` in the 429 body; the
    // component must read it and hold the resend button through that window.
    sendOtp().mockRejectedValue(
      new ApiError(429, "RATE_LIMITED", "raw server detail", {
        resendAfterSeconds: 12,
      }),
    );
    renderForm();

    await act(async () => {}); // flush the initial async send (-> 429)
    expect(sendOtp()).toHaveBeenCalledTimes(1);

    // The 429 carries a 12s cooldown -> resend stays disabled with a countdown.
    expect(screen.getByText(/ارسال مجدد تا/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(12000);
    });

    // Cooldown elapsed -> resend re-enables.
    expect(screen.getByRole("button", { name: "ارسال مجدد کد" })).toBeEnabled();
  });
});
