import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom ships no matchMedia, which the official shadcn Sidebar reads through
// useIsMobile(). Stub it so component tests exercise the real components.
if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// jsdom implements no layout, so Element.scrollIntoView does not exist. Radix's
// Select calls it on the highlighted option when the listbox opens, which made
// every test that picks from a Select throw. A no-op is the right stub: nothing
// observes scroll position in these tests.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

// Same reason: Radix measures the trigger to position the popup and reads
// getBoundingClientRect, which jsdom returns as all-zeros. Pointer capture is
// also absent and Radix calls it on pointer interactions.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
}

afterEach(() => {
  cleanup();
});
