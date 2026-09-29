#!/usr/bin/env node
// Token lint: fails if any raw hex colour literal appears outside src/styles/tokens.css.
// Run as part of `pnpm lint` (see docs/04-FRONTEND.md §9 "Tokens").
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname;
const ALLOWLIST = new Set(["styles/tokens.css"]);
const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g;
const EXTENSIONS = new Set([".ts", ".tsx", ".css"]);

let violations = [];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const rel = relative(ROOT, full);
    const s = statSync(full);
    if (s.isDirectory()) {
      if (entry === "node_modules") continue;
      walk(full);
      continue;
    }
    if (!EXTENSIONS.has(entry.slice(entry.lastIndexOf(".")))) continue;
    if (ALLOWLIST.has(rel)) continue;
    if (rel.endsWith(".gen.ts")) continue;
    const text = readFileSync(full, "utf8");
    const matches = text.match(HEX_RE);
    if (matches) {
      violations.push({ file: rel, matches });
    }
  }
}

walk(ROOT);

if (violations.length > 0) {
  console.error("Token lint failed: raw hex colours found outside src/styles/tokens.css:\n");
  for (const v of violations) {
    console.error(`  ${v.file}: ${v.matches.join(", ")}`);
  }
  console.error("\nUse a token (var(--...) / Tailwind utility) instead. See references/tokens.css.");
  process.exit(1);
}

console.log("Token lint: OK (no raw hex colours outside src/styles/tokens.css)");
