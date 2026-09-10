import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// ADR-023 thin client: the dev server proxies /api to the FastAPI backend so the
// browser always talks to one origin and CORS stays deny-by-default (review R2-2).
// Staging/nginx serves the same single-origin contract. Backend port follows the
// documented dev contract (setup-guide); override with HIVEOS_API_PORT when needed.
const API_DEV_TARGET = `http://127.0.0.1:${process.env.HIVEOS_API_PORT ?? "8100"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: API_DEV_TARGET,
        changeOrigin: true,
      },
    },
  },
});
