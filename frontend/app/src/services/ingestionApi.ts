import { request } from "./http";
import type { DocumentPage, IngestionConfigureResult, IngestionStatusResult } from "../types";

export const ingestionApi = {
  configureIngestion: (folderPath: string) =>
    request<IngestionConfigureResult>("POST", "/ingestion-folder/configure", { folderPath }),
  getIngestionStatus: () => request<IngestionStatusResult>("GET", "/ingestion-folder/status"),
  listDocuments: () => request<DocumentPage>("GET", "/documents"),
};
