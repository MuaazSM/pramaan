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
const EVIDENCE_ID = "ev_hiksim01";

const ROUTES: { name: string; path: string; ready?: (page: Page) => Promise<void>; scrollExpand?: boolean }[] = [
  { name: "login", path: "/login" },
  { name: "cases", path: "/cases", ready: login },
  { name: "case-overview", path: `/cases/${CASE_ID}`, ready: login },
  { name: "evidence-new", path: `/cases/${CASE_ID}/evidence/new`, ready: login },
  // F2: evidence detail, recordings, findings (docs/progress/F2.md).
  { name: "evidence-detail", path: `/cases/${CASE_ID}/evidence/${EVIDENCE_ID}`, ready: login },
  { name: "recordings", path: `/cases/${CASE_ID}/recordings`, ready: login },
  { name: "findings", path: `/cases/${CASE_ID}/findings`, ready: login },
  // F3a: review workspace. Its layout is viewport-fit (video grid + timeline split panes size
  // themselves from the content area's actual height), not scroll-taller-than-viewport like the
  // table/detail screens above — so it opts out of expandScrollContainers (which would force
  // `<main>` to `height: auto` and collapse the percentage-height split panes to 0).
  { name: "review", path: `/cases/${CASE_ID}/review`, ready: login, scrollExpand: false },
  { name: "design-gallery", path: "/design", ready: login },
];

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

/**
 * The authenticated layout (`_app/route.tsx`) is `.flex.h-screen.w-screen.overflow-hidden`, and
 * `ScreenShell`'s content area inside it is a nested `overflow-y-auto <main>` — so the page's
 * *document* never scrolls, only that inner pane does, and `page.screenshot({ fullPage })` alone
 * only captures one viewport's worth of it, silently truncating anything below the fold (found
 * while reviewing F2's evidence-detail screen, whose device-log table sits below the pipeline
 * panel; docs/progress/F2.md "Decisions"). Force the whole clipping chain to lay out at its full
 * content height for the screenshot only — every route re-navigates before the next capture, so
 * this never leaks into the real app.
 */
async function expandScrollContainers(page: Page) {
  await page.evaluate(() => {
    const root = document.getElementById("root");
    const appLayout = root?.firstElementChild;
    const main = document.querySelector("main");
    for (const el of [document.documentElement, document.body, root, appLayout, main]) {
      if (!(el instanceof HTMLElement)) continue;
      el.style.overflow = "visible";
      el.style.height = "auto";
    }
  });
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
        if (route.scrollExpand !== false) await expandScrollContainers(page);
        await page.screenshot({
          path: path.join(OUT_DIR, `${route.name}-${size.name}-${theme}.png`),
          fullPage: true,
        });
      }
    });
  }
}
