import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate vitest config: the app config (vite.config.ts) stays production-only.
// jsdom environment + jest-dom matchers via src/test/setup.ts.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
