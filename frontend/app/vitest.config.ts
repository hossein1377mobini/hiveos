import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Test-focused config, kept separate from vite.config.ts so the dev server's
// proxy/port settings stay untouched. jsdom environment + globals let the
// @testing-library matchers and auto-cleanup work out of the box.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "src/test/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
