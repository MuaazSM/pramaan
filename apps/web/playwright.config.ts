import { defineConfig, devices } from "@playwright/test";

/**
 * Screenshot + e2e runner for mock mode (docs/04-FRONTEND.md §8 visual QA loop).
 * `pnpm shots` runs the screenshot spec only; `just check-web` does not run Playwright
 * (browser download is heavy) — CI/QA runs it separately per the task brief.
 */
export default defineConfig({
  testDir: "./playwright",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "off",
  },
  webServer: {
    command: "pnpm build:mock-preview",
    url: "http://localhost:4173",
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
