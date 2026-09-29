import { test, type Page } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Visual QA screenshots (docs/04-FRONTEND.md §8): every built route, both themes, into
 * docs/ui/screenshots/<route>-<size>-<theme>.png. Runs against the mock-mode preview build
 * (see package.json's `build:mock-preview`, wired as this config's webServer).
 */

const OUT_DIR = path.resolve(__dirname, "../../../docs/ui/screenshots");
fs.mkdirSync(OUT_DIR, { recursive: true });

const SIZES = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x800", width: 1280, height: 800 },
];

const CASE_ID = "case_cr20260412";

const ROUTES: { name: string; path: string; ready?: (page: Page) => Promise<void> }[] = [
  { name: "login", path: "/login" },
  { name: "cases", path: "/cases", ready: login },
  { name: "case-overview", path: `/cases/${CASE_ID}`, ready: login },
  { name: "evidence-new", path: `/cases/${CASE_ID}/evidence/new`, ready: login },
  { name: "design-gallery", path: "/design", ready: login },
];

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.evaluate((t) => {
    document.documentElement.setAttribute("data-theme", t);
    try {
      localStorage.setItem("pramaan-ui", JSON.stringify({ state: { theme: t, density: "comfortable", sidebarCollapsed: false }, version: 0 }));
    } catch {
      /* ignore */
    }
  }, theme);
}

for (const size of SIZES) {
  for (const theme of ["dark", "light"] as const) {
    test(`${size.name} ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      for (const route of ROUTES) {
        if (route.ready) await route.ready(page);
        await page.goto(route.path);
        await setTheme(page, theme);
        await page.reload();
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(300);
        await page.screenshot({
          path: path.join(OUT_DIR, `${route.name}-${size.name}-${theme}.png`),
          fullPage: true,
        });
      }
    });
  }
}
