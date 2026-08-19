import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import OwnerAccount from "./OwnerAccount";
import { fillValidOwner, STRONG_PW, PHONE } from "../test/helpers";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      createOrganization: vi.fn(),
      createOwner: vi.fn(),
      sendOtp: vi.fn(),
      verifyOtp: vi.fn(),
      initializeWorkspace: vi.fn(),
      initializeBrain: vi.fn(),
      configureIngestion: vi.fn(),
      getIngestionStatus: vi.fn(),
      listDocuments: vi.fn(),
      getOnboardingStatus: vi.fn(),
      completeOnboarding: vi.fn(),
    },
  };
});

const createOwner = () => vi.mocked(api.createOwner);

function renderForm() {
  const onDone = vi.fn();
  const onBack = vi.fn();
  render(<OwnerAccount onDone={onDone} onBack={onBack} />);
  return { onDone, onBack };
}

describe("OwnerAccount", () => {
  beforeEach(() => {
    createOwner().mockReset();
  });

  const submit = () => screen.getByRole("button", { name: "ایجاد حساب" });

  it("rejects a phone that is not ^\\+98\\d{10}$", async () => {
    const user = userEvent.setup();
    const { onDone } = renderForm();
    await fillValidOwner(user, { phone: "912" }); // too short
    await user.click(submit());
    expect(await screen.findByText("شماره موبایل باید ۱۰ رقم بعد از ۹۸+ باشد.")).toBeInTheDocument();
    expect(createOwner()).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("accepts Persian-digit input and normalizes it to Latin before submitting", async () => {
    const user = userEvent.setup();
    renderForm();
    createOwner().mockResolvedValue({
      userId: "u1",
      organizationId: "org-1",
      status: "active",
      sessionIssued: true,
    });
    await fillValidOwner(user, { phone: "۹۱۲۳۴۵۶۷۸۹" });
    await user.click(submit());
    await waitFor(() => expect(createOwner()).toHaveBeenCalledTimes(1));
    expect(createOwner()).toHaveBeenCalledWith(
      expect.objectContaining({ phone: "+989123456789" }),
    );
  });

  it("toggles the password strength checklist and flags a confirm mismatch", async () => {
    const user = userEvent.setup();
    renderForm();

    const pwd = screen.getByLabelText(/^رمز عبور/);
    const confirm = screen.getByLabelText(/تکرار رمز عبور/);

    // weak password: checklist items that require it are not "ok"
    await user.type(pwd, "abc");
    expect(screen.getByText("حداقل ۸ کاراکتر")).not.toHaveClass("ok");
    expect(screen.getByText("یک حرف بزرگ")).not.toHaveClass("ok");

    // strong password: every checklist item becomes "ok"
    await user.clear(pwd);
    await user.type(pwd, STRONG_PW);
    for (const label of ["حداقل ۸ کاراکتر", "یک حرف بزرگ", "یک حرف کوچک", "یک عدد", "یک نماد"]) {
      expect(screen.getByText(label)).toHaveClass("ok");
    }

    // confirm mismatch
    await user.type(confirm, "Different1!");
    await user.click(submit());
    expect(await screen.findByText("تکرار رمز با رمز یکسان نیست.")).toBeInTheDocument();
    expect(createOwner()).not.toHaveBeenCalled();
  });

  it("submits phone/password/confirmPassword only (no email) and returns {userId, phone}", async () => {
    const user = userEvent.setup();
    const { onDone } = renderForm();
    createOwner().mockResolvedValue({
      userId: "u42",
      organizationId: "org-1",
      status: "active",
      sessionIssued: true,
    });

    await fillValidOwner(user);
    await user.click(submit());

    await waitFor(() => expect(createOwner()).toHaveBeenCalledTimes(1));
    expect(createOwner()).toHaveBeenCalledWith({
      phone: PHONE,
      password: STRONG_PW,
      confirmPassword: STRONG_PW,
    });
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith({ userId: "u42", phone: PHONE }),
    );
  });

  it("on 409 (phone taken) renders the curated Persian message and stays on the form", async () => {
    const user = userEvent.setup();
    const { onDone } = renderForm();
    createOwner().mockRejectedValue(new ApiError(409, "PHONE_TAKEN", "raw server detail"));

    await fillValidOwner(user);
    await user.click(submit());

    expect(await screen.findByText(/ثبت شده است/)).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
    // still on the form
    expect(screen.getByRole("heading", { name: "اطلاعات حساب مدیر" })).toBeInTheDocument();
    expect(submit()).toBeInTheDocument();
  });
});
