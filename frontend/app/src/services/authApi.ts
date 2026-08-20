import { request } from "./http";
import type { OwnerCreate, OtpSendRequest, OtpVerifyRequest } from "../types";

export const authApi = {
  createOwner: (p: OwnerCreate) =>
    request<{ userId: string; organizationId: string; status: string; sessionIssued: boolean }>(
      "POST",
      "/users/owner",
      p,
    ),
  sendOtp: (p: OtpSendRequest) =>
    request<{ status: string; resendAfterSeconds: number; expiresInSeconds: number }>(
      "POST",
      "/auth/send-otp",
      p,
    ),
  resendOtp: (p: OtpSendRequest) =>
    request<{ status: string; resendAfterSeconds: number; expiresInSeconds: number }>(
      "POST",
      "/auth/resend-otp",
      p,
    ),
  verifyOtp: (p: OtpVerifyRequest) =>
    request<{ verified: boolean; userStatus: string; organizationStatus: string }>(
      "POST",
      "/auth/verify-otp",
      p,
    ),
};
