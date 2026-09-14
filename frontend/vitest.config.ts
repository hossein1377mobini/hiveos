import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate vitest config: the app config (vite.config.ts) stays production-only.
// jsdom environment + jest-dom matchers via src/test/setup.ts.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // vitest's default glob is **/*.spec.* - without this it would try to run the
    // playwright specs in jsdom, where they fail for reasons that have nothing to
    // do with the code (no real browser, no navigations).
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules/**", "dist/**", "e2e/**"],
  },
});
