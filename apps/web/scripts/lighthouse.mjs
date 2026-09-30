#!/usr/bin/env node
// Lighthouse budget gate (docs/04-FRONTEND.md §7): "Lighthouse (desktop, mock mode): Performance
// >= 90, Accessibility >= 95." Runs against `vite preview` serving the mock-mode build, using the
// already-installed Playwright Chromium (chrome-launcher's `chromePath`) rather than downloading
// a second copy of Chrome — this machine has ~10GiB free (see docs/progress/F5.md "Fallbacks").
//
// Two routes are audited:
//   - /login   — cold, unauthenticated, no mock-API dependency: the most representative "first
//                load" measurement and the one this gate is enforced against.
//   - /cases   — audited best-effort in the *same* browser instance right after a scripted login
//                (Playwright, connected over CDP to the same Chromium), so the session cookie and
//                the registered mock-service-worker (origin-scoped, not per-tab) are both live for
//                Lighthouse's own fresh-tab navigation. Recorded for information; not gated, since
//                a failure here (e.g. a future MSW/timing change) shouldn't block the whole budget
//                check over a route Lighthouse was never designed to drive through app JS.
import { spawn } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import * as chromeLauncher from "chrome-launcher";
import lighthouse, { desktopConfig } from "lighthouse";
import { chromium as playwrightChromium } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.resolve(ROOT, "../../docs/ui/lighthouse");
fs.mkdirSync(OUT_DIR, { recursive: true });

const PORT = 4173;
const BASE = `http://localhost:${PORT}`;
const BUDGETS = { performance: 90, accessibility: 95 };

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: "inherit", cwd: ROOT });
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} ${args.join(" ")} exited ${code}`))));
  });
}

async function waitForServer(url, timeoutMs = 30_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`Server at ${url} did not become ready within ${timeoutMs}ms`);
}

async function audit(url, port) {
  const rt = await lighthouse(
    url,
    { port, output: "json", logLevel: "error", onlyCategories: ["performance", "accessibility"] },
    desktopConfig,
  );
  const performance = Math.round(rt.lhr.categories.performance.score * 100);
  const accessibility = Math.round(rt.lhr.categories.accessibility.score * 100);
  return { lhr: rt.lhr, performance, accessibility };
}

async function main() {
  console.log("== lighthouse: building mock-mode bundle ==");
  await run("pnpm", ["exec", "vite", "build", "--mode", "mock", "--outDir", "dist-mock"]);

  console.log("== lighthouse: starting preview server ==");
  const preview = spawn("pnpm", ["exec", "vite", "preview", "--outDir", "dist-mock", "--port", String(PORT), "--strictPort"], {
    cwd: ROOT,
    stdio: "inherit",
  });
  const stopPreview = () => preview.kill();
  process.once("exit", stopPreview);

  await waitForServer(BASE);

  const chromePath = playwrightChromium.executablePath();
  console.log("== lighthouse: launching the Playwright-installed Chromium ==", chromePath);
  const chrome = await chromeLauncher.launch({
    chromePath,
    chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
  });

  const results = [];
  let exitCode = 0;
  try {
    console.log("== lighthouse: auditing /login (gated) ==");
    const login = await audit(`${BASE}/login`, chrome.port);
    fs.writeFileSync(path.join(OUT_DIR, "login.json"), JSON.stringify(login.lhr, null, 2));
    results.push({ route: "/login", gated: true, ...login });
    console.log(`   performance=${login.performance} accessibility=${login.accessibility}`);

    try {
      console.log("== lighthouse: best-effort auditing /cases (authenticated, informational) ==");
      const browser = await playwrightChromium.connectOverCDP(`http://localhost:${chrome.port}`);
      const context = browser.contexts()[0] ?? (await browser.newContext());
      const page = await context.newPage();
      await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
      await page.getByLabel("Username").fill("examiner");
      await page.getByLabel("Password").fill("demo");
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.waitForURL("**/cases");
      await page.close();
      await browser.close(); // detaches the CDP session only; does not kill the launched Chrome

      const cases = await audit(`${BASE}/cases`, chrome.port);
      fs.writeFileSync(path.join(OUT_DIR, "cases.json"), JSON.stringify(cases.lhr, null, 2));
      results.push({ route: "/cases", gated: false, ...cases });
      console.log(`   performance=${cases.performance} accessibility=${cases.accessibility}`);
    } catch (err) {
      console.warn("   /cases audit skipped (informational only):", err.message);
    }

    fs.writeFileSync(
      path.join(OUT_DIR, "summary.json"),
      JSON.stringify(
        results.map(({ route, gated, performance, accessibility }) => ({ route, gated, performance, accessibility })),
        null,
        2,
      ),
    );

    console.log("\n== lighthouse: summary ==");
    for (const r of results) {
      const status = r.gated ? (r.performance >= BUDGETS.performance && r.accessibility >= BUDGETS.accessibility ? "PASS" : "FAIL") : "info";
      console.log(`${status.padEnd(4)} ${r.route.padEnd(10)} performance=${r.performance} (>=${BUDGETS.performance}) accessibility=${r.accessibility} (>=${BUDGETS.accessibility})`);
    }

    const gatedFailures = results.filter((r) => r.gated && (r.performance < BUDGETS.performance || r.accessibility < BUDGETS.accessibility));
    if (gatedFailures.length) {
      console.error("\nBudget miss(es):", gatedFailures.map((r) => r.route).join(", "));
      exitCode = 1;
    }
  } finally {
    await chrome.kill();
    stopPreview();
  }
  process.exitCode = exitCode;
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
