import { request } from "./http";
import type { CompleteOnboardingResult, OnboardingStatusResult } from "../types";

export const onboardingApi = {
  getOnboardingStatus: () => request<OnboardingStatusResult>("GET", "/onboarding/status"),
  completeOnboarding: () => request<CompleteOnboardingResult>("POST", "/onboarding/complete"),
};
