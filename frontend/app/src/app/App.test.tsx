import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { organizationApi } from "../services/organizationApi";
import { authApi } from "../services/authApi";
import { fillValidOrg, fillValidOwner, fillOtp, ORG_NAME, PHONE } from "../test/helpers";

vi.mock("../services/organizationApi", () => ({
  organizationApi: { createOrganization: vi.fn() },
}));

vi.mock("../services/authApi", () => ({
  authApi: { createOwner: vi.fn(), sendOtp: vi.fn(), resendOtp: vi.fn(), verifyOtp: vi.fn() },
}));

const createOrg = () => vi.mocked(organizationApi.createOrganization);
const createOwner = () => vi.mocked(authApi.createOwner);
const sendOtp = () => vi.mocked(authApi.sendOtp);
const verifyOtp = () => vi.mocked(authApi.verifyOtp);

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
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

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
