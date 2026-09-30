import { test, expect, type Page } from "@playwright/test";

/**
 * Mock e2e for F2 (evidence detail, recordings, findings) — docs/04-FRONTEND.md §9's "Mock e2e"
 * row, scoped to the three screens this task owns. Runs against the same mock-mode preview build
 * as `shots.spec.ts` (shared `webServer` in playwright.config.ts).
 */

const CASE_ID = "case_cr20260412";
const TIER_A_EVIDENCE_ID = "ev_hiksim01";
const TIER_B_EVIDENCE_ID = "ev_gensim02";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test.describe("F2 mock e2e", () => {
  test("evidence detail: identification, live scan pipeline, device log table", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/evidence/${TIER_A_EVIDENCE_ID}`);

    // Identification panel — ranked vendor match with OEM lineage, honesty-copy wording.
    await expect(page.getByText("HIKSIM · synthetic, Hikvision-style layout")).toBeVisible();
    await expect(page.getByText(/Hikvision-compatible/)).toHaveCount(0);
    await expect(page.getByText("OEM lineage", { exact: false })).toBeVisible();

    // Scan pipeline — starts "done" from the seeded job; clicking Run scan starts a fresh one that
    // streams over the mock WS (src/mocks/ws-handlers.ts) through to "done" again.
    await expect(page.getByText("done", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Run scan" }).click();
    await expect(page.getByText("Scan started", { exact: false })).toBeVisible();
    await expect(page.getByText("done", { exact: true }).first()).toBeVisible({ timeout: 10_000 });

    // Device log events table — at least the hdd_format and time_change rows from the fixture.
    await expect(page.getByText("hdd format", { exact: false })).toBeVisible();
    await expect(page.getByText("time change", { exact: false })).toBeVisible();
  });

  test("evidence detail: Tier B inferred-layout panel, Confirm layout", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/evidence/${TIER_B_EVIDENCE_ID}`);

    await expect(page.getByText("Inferred layout")).toBeVisible();
    await expect(page.getByText("Tier B · structure inferred, not vendor-confirmed")).toBeVisible();
    await expect(page.getByRole("cell", { name: "magic" })).toBeVisible();

    await page.getByRole("button", { name: "Confirm layout" }).click();
    await expect(page.getByText("Confirmed by examiner")).toBeVisible();
  });

  test("recordings: filters narrow the table and Open in review navigates", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/recordings`);

    await expect(page.getByText("60 of 60 recordings")).toBeVisible();

    // Channel filter chip: 15 slices on CH2 (out of 60 total across 4 channels).
    await page.getByRole("button", { name: "CH2" }).click();
    await expect(page.getByText("15 of 60 recordings")).toBeVisible();

    // Status filter: Recovered only (4 of CH2's 15 slices overlap the 13h deletion window).
    await page.getByRole("button", { name: "Recovered" }).click();
    await expect(page.getByText("4 of 60 recordings")).toBeVisible();
    await expect(page.getByText("recovered").first()).toBeVisible();

    await page.getByRole("link", { name: "Open in review" }).first().click();
    await page.waitForURL(`**/cases/${CASE_ID}/review`);
  });

  test("findings: verdict card content and Open evidence navigates", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/findings`);

    await expect(page.getByText("Format deletion · CH3")).toBeVisible();
    await expect(page.getByText("admin", { exact: true })).toBeVisible();
    await expect(page.getByText("214")).toBeVisible();
    await expect(page.getByText(/hdd_format log event/)).toBeVisible();

    await page.getByRole("link", { name: "Open evidence" }).click();
    await page.waitForURL(`**/cases/${CASE_ID}/evidence/${TIER_A_EVIDENCE_ID}`);
  });
});
