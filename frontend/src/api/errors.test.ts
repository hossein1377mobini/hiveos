import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { persianError } from "./errors";

/**
 * Every error the API can return must reach the owner in Persian.
 *
 * The PO requirement is that no English developer string is ever shown. The map
 * in errors.ts is what enforces that, but nothing stopped a new backend code
 * from shipping without an entry: it would fall through to the status fallback
 * and the owner would read a generic sentence, or - for a code with no matching
 * status - the raw English message.
 *
 * INFERENCE_BUSY is the case that prompted this: it was added to the backend by
 * the load-shedding change, and the frontend had no wording for it yet.
 */
describe("persianError", () => {
  it("explains a shed request as busy rather than unavailable", () => {
    // The retry instruction is the point: this is a deliberate refusal under
    // load, not an outage, so the owner must be told to try again.
    const text = persianError("INFERENCE_BUSY", 503);
    expect(text).toContain("مشغول");
    expect(text).toContain("دوباره تلاش");
    expect(text).not.toContain("INFERENCE_BUSY");
  });

  it("never returns the English server message for an unknown code", () => {
    const text = persianError("SOME_UNKNOWN_CODE", 500, "Internal Server Error");
    expect(text).not.toMatch(/[A-Za-z]/);
  });

  it("keeps a server message that is already Persian", () => {
    const text = persianError("SOME_UNKNOWN_CODE", 400, "این پیام از سرور است.");
    expect(text).toBe("این پیام از سرور است.");
  });
});

/** Collect the codes the backend actually raises, straight from its source. */
function backendErrorCodes(): string[] | null {
  const roots = [
    resolve(__dirname, "../../../backend/backend"),
    resolve(__dirname, "../../backend/backend"),
  ];
  const root = roots.find((candidate) => existsSync(candidate));
  if (!root) return null;

  const codes = new Set<string>();
  // ApiError(status, "CODE", ...) is the only shape the backend raises.
  const pattern = /ApiError\(\s*\d+\s*,\s*"([A-Z][A-Z0-9_]+)"/g;
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = resolve(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".py")) {
        for (const match of readFileSync(full, "utf8").matchAll(pattern)) {
          codes.add(match[1]);
        }
      }
    }
  };
  walk(root);
  return [...codes];
}

describe("the message map covers the backend", () => {
  it("has Persian wording for every code the API raises", () => {
    const codes = backendErrorCodes();
    if (codes === null) {
      // The backend tree is not next to the frontend in every checkout (a
      // built image ships only one of them); skip rather than fail on layout.
      return;
    }
    // Guard against the scan silently finding nothing: a regex that stops
    // matching would otherwise make this test pass by covering zero codes.
    expect(codes.length).toBeGreaterThan(50);
    const missing = codes.filter((code) => {
      const text = persianError(code, 400, null);
      // A mapped code returns its own sentence; an unmapped one gets the
      // generic status fallback, which is the signal this test is after.
      return text.startsWith("درخواست شما پذیرفته نشد");
    });
    expect(missing, `no Persian message for: ${missing.join(", ")}`).toEqual([]);
  });
});
