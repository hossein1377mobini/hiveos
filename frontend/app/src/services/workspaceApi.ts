import { request } from "./http";
import type { WorkspaceInitResult } from "../types";

export const workspaceApi = {
  initializeWorkspace: () => request<WorkspaceInitResult>("POST", "/workspaces/initialize"),
};
