#!/usr/bin/env node
/**
 * Resolved-token gate - the shadow bug this exists to prevent.
 *
 * scripts/ui-audit.mjs checks that components USE the tokens, and it passed
 * while every shadow in the product rendered box-shadow:none. The cause was a
 * circular declaration: @theme inline repeated "--shadow-card: var(--shadow-card)",
 * which shadows the literal declared in @theme. A circular var() resolves to the
 * empty string instead of erroring, so the class compiled, the audit saw the
 * class name, and the elevation was invisible.
 *
 * This gate therefore checks the value a utility actually RESOLVES to, following
 * var() indirection (rounded-card -> var(--radius-card) -> 14px is correct) and
 * failing on the shapes that silently produce nothing: a circular reference, or a
 * reference to a variable that is never declared.
 *
 * It reads the built stylesheet, which CI produces with "npm run build".
 *
 * Usage: node scripts/check-css-tokens.mjs
 */
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const ASSETS = join(ROOT, "dist", "assets");

/** Utility -> a substring the fully-resolved value must contain. */
const EXPECTED = {
  // Cursor's system is hairline-only: "Don't add drop shadows. Hairlines +
  // ink-on-cream contrast carry the depth." Card and raised elevation are
  // therefore intentionally "none", and this gate asserts that rather than a
  // pixel value - the point of the check is that a token resolves to something
  // deliberate, and "none" is deliberate here. A regression that made these
  // empty would resolve to "", which is still caught.
  "shadow-card": "none",
  "shadow-raised": "none",
  // The one surviving elevation: a dialog or dropdown floats above arbitrary
  // content where a hairline cannot separate it.
  "shadow-pop": "0 10px 28px",
  // Resolves to the accent hex, not to var(--color-accent-400): Tailwind inlines
  // the colour into --tw-shadow-color, which is exactly the healthy outcome.
  "shadow-focus": "0 0 0 1px",
  // Cursor radius scale: md 8 for CTAs/inputs, lg 12 for cards.
  "rounded-card": "12px",
  "rounded-control": "8px",
  "rounded-xs": "6px",
};

if (!existsSync(ASSETS)) {
  console.error("check-css-tokens: dist/assets is missing - run \`npm run build\` first.");
  process.exit(1);
}
const cssFile = readdirSync(ASSETS).find((f) => f.endsWith(".css"));
if (!cssFile) {
  console.error("check-css-tokens: no built stylesheet in dist/assets.");
  process.exit(1);
}
const css = readFileSync(join(ASSETS, cssFile), "utf8");

/** Every custom property declared anywhere, last declaration winning. */
const declared = new Map();
for (const m of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;}]+)/g)) {
  declared.set(m[1], m[2].trim());
}

/**
 * Substitute var(--x) references until a concrete value remains.
 * Returns { value, error } - error names a cycle or an undeclared reference,
 * because both render as nothing while looking perfectly correct in the source.
 */
function resolve(value, seen = []) {
  const refs = [...value.matchAll(/var\(\s*(--[a-z0-9-]+)\s*\)/g)];
  let out = value;
  for (const [whole, name] of refs) {
    if (seen.includes(name)) return { error: "circular reference " + [...seen, name].join(" -> ") };
    const next = declared.get(name);
    if (next === undefined) {
      // Tailwind emits colour helpers like --tw-shadow-color at use time.
      if (name.startsWith("--tw-")) continue;
      return { error: "references undeclared " + name };
    }
    const inner = resolve(next, [...seen, name]);
    if (inner.error) return inner;
    out = out.replace(whole, inner.value);
  }
  return { value: out };
}

const failures = [];
for (const [cls, expected] of Object.entries(EXPECTED)) {
  const match = new RegExp("\\." + cls + "\\{([^}]*)\\}").exec(css);
  if (!match) { failures.push("." + cls + " is not in the built CSS at all"); continue; }
  const body = match[1];
  // Resolve first: the value may legitimately arrive through an indirection
  // (rounded-card -> var(--radius-card) -> 14px), which is correct and must not
  // be reported as a failure.
  const r = resolve(body);
  if (r.error) {
    failures.push("." + cls + " " + r.error + " - got: " + body.slice(0, 110));
  } else if (!r.value.includes(expected)) {
    failures.push("." + cls + " does not resolve to a value containing \"" + expected + "\" - got: " + r.value.slice(0, 110));
  }
}

// Global sweep: any custom property that resolves to empty or to itself.
const circular = [];
for (const [name, value] of declared) {
  const own = value.match(/^var\(\s*(--[a-z0-9-]+)\s*\)$/);
  if (own && own[1] === name) circular.push(name);
}
if (circular.length) {
  failures.push("self-referential custom properties resolve to empty: " + circular.join(", "));
}

if (failures.length) {
  console.error("check-css-tokens: " + failures.length + " failure(s) in " + cssFile + "\n");
  for (const f of failures) console.error("  FAIL " + f);
  console.error("\nA token that resolves to nothing renders nothing.");
  process.exit(1);
}

console.log("check-css-tokens: " + cssFile + " - " + Object.keys(EXPECTED).length + " tokens resolve to real values");
