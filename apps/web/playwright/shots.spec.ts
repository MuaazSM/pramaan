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
// F3b: prove-it / frame inspector. FRAME_ID is an ordinary CH2 frame (verified state);
// MISMATCH_FRAME_ID must stay in sync with src/mocks/prove-fixtures.ts's DEMO_MISMATCH_FRAME_ID
// (the one frame the mock hex handler deliberately mismatches, so the danger/mismatch integrity
// state has a real screen for the visual QA loop and gallery to review).
const FRAME_ID = "frm_ch2_0010";
const MISMATCH_FRAME_ID = "frm_ch1_0050";

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
  // F3b: prove-it hex view + frame inspector (docs/progress/F3b.md). Two states: an ordinary
  // frame (verified — the common case) and the deliberately-mismatched demo frame, which is the
  // "inspector gallery/demo state" the task brief asks for — the danger/mismatch integrity state
  // otherwise never appears in any other screenshot in this repo.
  { name: "prove-it", path: `/cases/${CASE_ID}/frames/${FRAME_ID}/prove`, ready: login },
  { name: "prove-it-mismatch", path: `/cases/${CASE_ID}/frames/${MISMATCH_FRAME_ID}/prove`, ready: login },
  // F4: reports, exports, custody, settings (docs/progress/F4.md).
  { name: "reports", path: `/cases/${CASE_ID}/reports`, ready: login },
  { name: "exports", path: `/cases/${CASE_ID}/exports`, ready: login },
  { name: "custody", path: `/cases/${CASE_ID}/custody`, ready: login },
  { name: "settings", path: "/settings", ready: login },
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
 * panel; docs/progress/F2.md "Decisions").
 *
 * F5 fix: this used to force `overflow: visible; height: auto` on the document/root/main chain
 * for the screenshot. That broke the sidebar and custody-seal footer, which stretch to the app
 * shell's height via `h-full`/flex `align-items: stretch` against the shell's `h-screen` —
 * percentage/stretch sizing against a container whose height was hacked to `auto` resolves to
 * the *sidebar's own* short content height, so it (and the footer) stopped mid-page in the
 * full-page capture even though the real, unmodified app always fills the viewport (`h-screen`
 * is exact by construction; only `main` ever scrolls internally). Rather than fight flexbox
 * stretch semantics with more CSS overrides, grow the real browser viewport to `main`'s natural
 * content height before shooting, so the shell's `h-screen`/`h-full` chain is never touched —
 * the sidebar and footer lay out exactly as they do in the running app, just at a taller
 * viewport, and `fullPage` screenshot then needs no scrolling to capture everything.
 */
async function scrollContainerOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const main = document.querySelector("main");
    if (!(main instanceof HTMLElement)) return 0;
    return Math.max(0, main.scrollHeight - main.clientHeight);
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
      for (const route of ROUTES) {
        // Reset to the base viewport before every route: a previous route may have grown it to
        // fit tall content (below), and `ready()`/login must run at the real, un-grown size.
        await page.setViewportSize({ width: size.width, height: size.height });
        if (route.ready) await route.ready(page);
        await page.goto(route.path);
        await setTheme(page, theme);
        await page.reload();
        await page.waitForLoadState("networkidle");
        // 700ms (not 300ms): long enough for the prove-it screen's SHA-256 recompute animation
        // (features/prove/components/sha-recompute.tsx's 480ms perceivable-computing delay) to
        // settle to its verified/mismatch state before the screenshot, not the transient spinner.
        await page.waitForTimeout(700);
        if (route.scrollExpand !== false) {
          const extra = await scrollContainerOverflow(page);
          if (extra > 0) {
            await page.setViewportSize({ width: size.width, height: size.height + extra });
            // The resize can trigger a layout pass (virtualized tables, ResizeObservers); let it settle.
            await page.waitForTimeout(120);
          }
        }
        await page.screenshot({
          path: path.join(OUT_DIR, `${route.name}-${size.name}-${theme}.png`),
          fullPage: true,
        });
      }
    });
  }
}
