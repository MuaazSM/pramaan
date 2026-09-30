import { test, expect, type Page } from "@playwright/test";

/**
 * Mock e2e for F4 (Reports screen). Runs against the same mock-mode preview build as
 * `shots.spec.ts` (shared `webServer` in playwright.config.ts). The mock `HEALTH.llm_enabled` is
 * false, so this also checks the CLAUDE.md rule-6-adjacent behaviour: with the LLM off, the AI
 * draft section is absent from the page entirely.
 */

const CASE_ID = "case_cr20260412";
const SEED_REPORT_ID = "rpt_7c1e4a90b2d3";
const NEW_REPORT_ID = "rpt_e5b8c204a1f9";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test.describe("F4 mock e2e", () => {
  test("reports: list, generate, download links, manifest, AI draft hidden when LLM off", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/reports`);

    await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
    // Breadcrumb resolves the case number instead of showing the raw id.
    await expect(page.getByRole("navigation", { name: "Lineage" }).getByText("CR-2026-0412")).toBeVisible();

    // Seeded report is listed, with a verified sha256 integrity chip.
    const rows = page.getByTestId("report-row");
    await expect(rows).toHaveCount(1);
    await expect(rows.first().getByText(SEED_REPORT_ID)).toBeVisible();
    await expect(rows.first().getByText("verified", { exact: true })).toBeVisible();
    await expect(rows.first().getByText(/sha256 7c1e4a90…c204/)).toBeVisible();

    // Generate a report; it appears as the newest row.
    await page.getByRole("button", { name: "Generate report" }).click();
    await expect(rows).toHaveCount(2);
    await expect(rows.first().getByText(NEW_REPORT_ID)).toBeVisible();
    await expect(rows.first().getByText("latest")).toBeVisible();
    await expect(rows.first().getByText("verified", { exact: true })).toBeVisible();
    await expect(rows.first().getByText(/sha256 e5b8c204…c470/)).toBeVisible();

    // PDF / certificate are real links to the API paths; manifest is a toggle.
    const newest = rows.first();
    await expect(newest.getByRole("link", { name: "PDF" })).toHaveAttribute("href", `/api/reports/${NEW_REPORT_ID}/pdf`);
    await expect(newest.getByRole("link", { name: "BSA §63 certificate" })).toHaveAttribute(
      "href",
      `/api/reports/${NEW_REPORT_ID}/certificate.pdf`,
    );
    await expect(newest.getByRole("link", { name: "PDF" })).toHaveAttribute("target", "_blank");

    // Manifest opens as key rows + hash list + limitations (not raw JSON).
    await newest.getByRole("button", { name: "Manifest" }).click();
    const manifest = newest.getByTestId("manifest-view");
    await expect(manifest.getByText("CR-2026-0412 · Shopfront burglary, Andheri")).toBeVisible();
    await expect(manifest.getByText("Evidence hashes")).toBeVisible();
    await expect(manifest.getByText(/a41f09c2b8d3e6710f4c9a2b5e8d1f0c/)).toBeVisible();
    await expect(manifest.getByText(/^Synthetic corpus/)).toBeVisible();

    // With HEALTH.llm_enabled false (assert it, so the absence check below can't be vacuous), the
    // AI draft section must not exist at all — not merely be disabled.
    const health = await page.evaluate(() => fetch("/api/system/health").then((r) => r.json() as Promise<{ llm_enabled: boolean }>));
    expect(health.llm_enabled).toBe(false);
    await expect(page.getByTestId("ai-draft-section")).toHaveCount(0);
    await expect(page.getByText("AI draft", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Draft narrative/ })).toHaveCount(0);
  });
});
