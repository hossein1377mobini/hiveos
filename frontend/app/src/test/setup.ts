// Vitest setup: register jest-dom's DOM matchers on Vitest's `expect`.
// The `/vitest` entry augments Vitest's Assertion interface (not jest), so
// matchers like `toBeInTheDocument` / `toHaveTextContent` are typed + runtime-ready.
import "@testing-library/jest-dom/vitest";
