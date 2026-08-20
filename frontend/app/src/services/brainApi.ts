import { request } from "./http";
import type { BrainInitResult } from "../types";

export const brainApi = {
  initializeBrain: () => request<BrainInitResult>("POST", "/brain/initialize"),
};
