#!/usr/bin/env node
/**
 * Bundle budget gate. [F4]
 *
 * Performance budgets that live only in a document are aspirations. This asserts
 * them against the real build output, so a dependency that doubles the initial
 * payload fails CI instead of being noticed after a release.
 *
 * The numbers are deliberately ceilings with headroom, not targets: a budget
 * that has to be raised on every feature is one that gets deleted. What they
 * catch is a step change - a charting library, a date library, an icon set
 * imported wholesale.
 *
 * Run after the vite build: node scripts/check-bundle-budget.mjs
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { basename, join } from "node:path";

const DIST = fileURLToPath(new URL("../dist/", import.meta.url));

/** Ceilings in kB. The entry chunk and CSS are what block first paint. */
const LIMITS = {
  entryJsGzip: 190,
  cssGzip: 30,
  totalJsGzip: 420,
};

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const files = walk(DIST);
const gz = (file) => gzipSync(readFileSync(file), { level: 9 }).length / 1024;
const base = (file) => basename(file);

// Vite names the entry index-<hash>.js; route chunks carry their own names.
const js = files.filter((f) => f.endsWith(".js")).map((f) => ({ name: base(f), kb: gz(f) }));
const css = files.filter((f) => f.endsWith(".css")).map((f) => ({ name: base(f), kb: gz(f) }));

const entry = js.find((f) => /^index-.*\.js$/.test(f.name));
if (!entry) {
  console.error("no entry chunk found in dist/ - did the build run?");
  process.exit(1);
}

const cssTotal = css.reduce((sum, f) => sum + f.kb, 0);
const jsTotal = js.reduce((sum, f) => sum + f.kb, 0);

const checks = [
  { label: "entry js (gzip)", actual: entry.kb, limit: LIMITS.entryJsGzip },
  { label: "css (gzip)", actual: cssTotal, limit: LIMITS.cssGzip },
  { label: "total js (gzip)", actual: jsTotal, limit: LIMITS.totalJsGzip },
];

let failed = false;
for (const { label, actual, limit } of checks) {
  const over = actual > limit;
  if (over) failed = true;
  console.log(
    (over ? "FAIL " : "ok   ") +
      label.padEnd(18) +
      actual.toFixed(2).padStart(8) +
      " kB / " + String(limit).padStart(4) + " kB  (" + ((actual / limit) * 100).toFixed(0) + "%)",
  );
}

// The heaviest route chunks, so a regression is attributable without guessing.
const heaviest = [...js].sort((a, b) => b.kb - a.kb).slice(0, 5);
console.log("\nheaviest chunks:");
for (const f of heaviest) console.log("  " + f.name.padEnd(30) + f.kb.toFixed(2) + " kB");

if (failed) {
  console.error("\nbundle budget exceeded");
  process.exit(1);
}
console.log("\nwithin budget");
