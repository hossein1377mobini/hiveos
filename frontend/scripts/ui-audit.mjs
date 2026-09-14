#!/usr/bin/env node
/**
 * UI drift audit — the number, not the adjective.
 *
 * The UI defect register demands "every finding carries a file and line". This
 * script is that rule applied to the design system itself: it counts every
 * place a component bypasses a token and prints the offending locations.
 *
 * Rules (all fail the gate at 0 allowed, except the informational ones):
 *   radius-adhoc      rounded-[Npx]                  -> use rounded-xs|control|card
 *   radius-legacy     rounded-sm|md|lg|xl|2xl        -> legacy shadcn ladder, retiring
 *   shadow-legacy     shadow-sm|md|lg|xl|2xl         -> use shadow-card|raised|pop
 *   shadow-adhoc      shadow-[...]                   -> use shadow-card|raised|pop
 *   type-adhoc        text-[Npx]                     -> use text-display|title|...
 *   weight-offscale   font-extrabold|black           -> ladder is 400/500/600/700
 *   motion-blanket    transition-all                 -> name the property
 *   color-raw         bg-red-500 etc                 -> use a semantic role
 *
 * Usage:  node scripts/ui-audit.mjs [--json] [--quiet]
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const SRC = join(ROOT, "src");

/** Each rule: id, why it exists, and how to fix it. */
export const RULES = [
  {
    id: "radius-adhoc",
    pattern: /rounded-\[[0-9.]+px\]/g,
    fix: "rounded-xs (6) | rounded-control (9) | rounded-card (14)",
  },
  {
    id: "radius-legacy",
    pattern: /\brounded-(?:sm|md|lg|xl|2xl)\b/g,
    fix: "the semantic ladder: rounded-xs | rounded-control | rounded-card",
  },
  {
    id: "shadow-legacy",
    pattern: /\bshadow-(?:sm|md|lg|xl|2xl)\b/g,
    fix: "shadow-card | shadow-raised | shadow-pop",
  },
  {
    id: "shadow-adhoc",
    pattern: /shadow-\[/g,
    fix: "shadow-card | shadow-raised | shadow-pop",
  },
  {
    id: "type-adhoc",
    pattern: /text-\[[0-9.]+px\]/g,
    fix: "text-display | title | heading | subheading | body | caption | micro",
  },
  {
    id: "weight-offscale",
    pattern: /\bfont-(?:extrabold|black)\b/g,
    fix: "the weight ladder is 400/500/600/700 -> font-bold",
  },
  {
    id: "motion-blanket",
    pattern: /\btransition-all\b/g,
    fix: "transition-colors | transition-transform | transition-shadow",
  },
  {
    id: "color-raw",
    pattern:
      /\b(?:bg|text|border|ring|from|to|via)-(?:red|green|blue|yellow|orange|slate|zinc|gray|grey|indigo|purple|pink|emerald|teal|amber|violet|rose|sky|lime|cyan|fuchsia)-[0-9]{2,3}\b/g,
    fix: "a semantic role: primary | success | warning | error | info",
  },
];

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

/**
 * A class inside a comment is prose, not code. Blanking must preserve newlines:
 * collapsing a multi-line block comment shifts every line number after it, and
 * a finding whose line is wrong is not evidence.
 */
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "))
    .replace(/^([ \t]*)\/\/.*$/gm, "$1");
}

export function audit() {
  const files = walk(SRC);
  const findings = [];
  for (const file of files) {
    const lines = stripComments(readFileSync(file, "utf8")).split(/\r?\n/);
    lines.forEach((line, index) => {
      for (const rule of RULES) {
        rule.pattern.lastIndex = 0;
        const hits = line.match(rule.pattern);
        if (!hits) continue;
        for (const hit of hits) {
          findings.push({
            rule: rule.id,
            file: relative(ROOT, file).split(sep).join("/"),
            line: index + 1,
            match: hit,
            fix: rule.fix,
          });
        }
      }
    });
  }
  return { files: files.length, findings };
}

const byRule = (findings) => {
  const counts = {};
  for (const f of findings) counts[f.rule] = (counts[f.rule] ?? 0) + 1;
  return counts;
};

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith("ui-audit.mjs")) {
  const json = process.argv.includes("--json");
  const quiet = process.argv.includes("--quiet");
  const { files, findings } = audit();
  if (json) {
    console.log(JSON.stringify({ files, total: findings.length, byRule: byRule(findings), findings }, null, 2));
  } else {
    const counts = byRule(findings);
    console.log(`ui-audit: ${files} source files, ${findings.length} token bypasses\n`);
    for (const rule of RULES) {
      const n = counts[rule.id] ?? 0;
      const mark = n === 0 ? "ok  " : "FAIL";
      console.log(`  ${mark} ${rule.id.padEnd(16)} ${String(n).padStart(3)}   -> ${rule.fix}`);
    }
    if (!quiet && findings.length) {
      console.log("");
      for (const rule of RULES) {
        const list = findings.filter((f) => f.rule === rule.id);
        if (!list.length) continue;
        console.log(`\n${rule.id} (${list.length}):`);
        for (const f of list) console.log(`  ${f.file}:${f.line}  ${f.match}`);
      }
    }
  }
  process.exit(findings.length ? 1 : 0);
}
