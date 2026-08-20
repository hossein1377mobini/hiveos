import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import App from "./App";
import { fillValidOrg, fillValidOwner, fillOtp, ORG_NAME, PHONE } from "./test/helpers";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    api: {
      createOrganization: vi.fn(),
      createOwner: vi.fn(),
      sendOtp: vi.fn(),
      resendOtp: vi.fn(),
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

const createOrg = () => vi.mocked(api.createOrganization);
const createOwner = () => vi.mocked(api.createOwner);
const sendOtp = () => vi.mocked(api.sendOtp);
const verifyOtp = () => vi.mocked(api.verifyOtp);

describe("App onboarding wizard", () => {
  beforeEach(() => {
    createOrg().mockReset();
    createOwner().mockReset();
    sendOtp().mockReset();
    verifyOtp().mockReset();

    createOrg().mockResolvedValue({
      id: "org-1",
      name: ORG_NAME,
      status: "pending",
      tenantId: "t1",
      workspaceId: "w1",
      createdAt: "2026-08-19T00:00:00Z",
    });
    createOwner().mockResolvedValue({
      userId: "u1",
      organizationId: "org-1",
      status: "active",
      sessionIssued: true,
    });
    sendOtp().mockResolvedValue({ status: "sent", resendAfterSeconds: 30, expiresInSeconds: 120 });
    verifyOtp().mockResolvedValue({ verified: true, userStatus: "active", organizationStatus: "active" });
  });

  it("starts at RegisterOrganization and walks to OtpVerify with the owner's phone", async () => {
    const user = userEvent.setup();
    render(<App />);

    // step 0: RegisterOrganization
    expect(screen.getByRole("heading", { name: "اطلاعات سازمان" })).toBeInTheDocument();

    await fillValidOrg(user);
    await user.click(screen.getByRole("button", { name: "ساخت سازمان" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "اطلاعات حساب مدیر" })).toBeInTheDocument());

    // step 1 -> 2: OwnerAccount (Persian digits) advances to OtpVerify
    await fillValidOwner(user, { phone: "۹۱۲۳۴۵۶۷۸۹" });
    await user.click(screen.getByRole("button", { name: "ایجاد حساب" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "کد ۶ رقمی" })).toBeInTheDocument());

    // OtpVerify received the exact phone the owner used (normalized to Latin)
    await waitFor(() => expect(sendOtp()).toHaveBeenCalledWith({ phone: PHONE }));

    // verify uses that same phone
    fillOtp("123456");
    await user.click(screen.getByRole("button", { name: "تأیید" }));
    await waitFor(() => expect(verifyOtp()).toHaveBeenCalledWith({ phone: PHONE, code: "123456" }));
  });
});
