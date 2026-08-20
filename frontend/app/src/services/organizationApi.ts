import { request } from "./http";
import type { Organization, OrganizationCreate } from "../types";

export const organizationApi = {
  createOrganization: (p: OrganizationCreate) => request<Organization>("POST", "/organizations", p),
};
