import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND = "http://localhost:8100";

// Dev server proxies /api to the HiveOS backend so the onboarding/session
// cookies set by the API are stored on the SPA origin and sent automatically.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5199, // pinned — 5173 is used by the separate Kaneo dev server
    strictPort: false,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
    },
  },
});
