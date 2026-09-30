import { defineConfig, devices } from "@playwright/test";

/**
 * Real-mode e2e runner (docs/04-FRONTEND.md §9 "Real e2e": same flow as the mock e2e spec, but
 * against the real API on the synthetic corpus). Unlike `playwright.config.ts` (mock mode, builds
 * a static preview bundle), this targets the real Vite dev server (`pnpm dev`, real API proxy —
 * `vite.config.ts`'s `/api -> http://localhost:8000`) so every request hits FastAPI for real.
 *
 * Prerequisites (not started by this config — real-mode data takes minutes to seed via the scan
 * pipeline, too slow for Playwright's own `webServer` timeout budget):
 *   1. A real-mode API already running and reachable at http://localhost:8000, with the demo case
 *      seeded — `uv run python tools/demo/demo.py --keep-running --port 8000` (see docs/progress/QD.md).
 *   2. This config's own `webServer` starts the web dev server (`pnpm dev`, real mode — VITE_MOCK
 *      unset) pointing at that already-running API.
 *
 * Run: `pnpm -C apps/web exec playwright test -c playwright.real.config.ts`
 */
export default defineConfig({
  testDir: "./playwright",
  testMatch: /real-.*\.spec\.ts/,
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
