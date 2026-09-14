import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

// ADR-023 thin client: the dev server proxies /api to the FastAPI backend so the
// browser always talks to one origin and CORS stays deny-by-default (review R2-2).
// Staging/nginx serves the same single-origin contract. Backend port follows the
// documented dev contract (setup-guide); override with HIVEOS_API_PORT when needed.
// loadEnv (R5-3) keeps this config on vite's typed env surface.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "HIVEOS_");
  return {
    plugins: [react(), tailwindcss()],
    // Path alias @/* → src/* (shadcn/ui convention; required by the CLI).
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${env.HIVEOS_API_PORT || "8100"}`,
          changeOrigin: true,
        },
      },
    },
  };
});
