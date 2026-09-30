import { test, expect, type Page } from "@playwright/test";

/**
 * F4 mock e2e — custody screen (hash-chain audit log, verification, anchors). Runs against the
 * mock-mode preview build (playwright.config.ts's webServer), like the other f*-*.spec.ts files.
 * Needs custody-handlers.ts merged into src/mocks/handlers.ts (anchors endpoints).
 */

const CASE_ID = "case_cr20260412";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test.describe("F4 custody mock e2e", () => {
  test("audit timeline, re-verify, create local anchor, fabric anchor 501 surfaced", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/custody`);

    // Breadcrumb resolves the human case number, not the raw id.
    await expect(page.getByRole("navigation", { name: "Lineage" })).toContainText("CR-2026-0412");
    await expect(page.getByRole("heading", { name: "Custody", level: 1 })).toBeVisible();

    // Audit timeline renders the first page (25 of 128), "Load more" appends the next page.
    const entries = page.getByTestId("audit-entry");
    await expect(entries).toHaveCount(25);
    await expect(entries.first()).toContainText("case.created");
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(entries).toHaveCount(50);

    // Re-verify chain shows an ok result.
    await page.getByRole("button", { name: "Re-verify chain" }).click();
    const result = page.getByTestId("verify-result");
    await expect(result).toContainText("chain ok");
    await expect(result).toContainText("128");

    // Seeded anchor is listed; creating a local anchor adds a second row.
    const anchorRows = page.getByTestId("anchor-row");
    await expect(anchorRows).toHaveCount(1);
    await page.getByRole("button", { name: "Create anchor" }).click();
    await expect(anchorRows).toHaveCount(2);
    await expect(anchorRows.first()).toContainText("local");
    await expect(anchorRows.first()).toContainText("#1–#128");

    // Fabric is interface-only: the 501 must surface as an inline error, not a crash / blank screen.
    await page.getByRole("combobox", { name: "Anchor backend" }).click();
    await page.getByRole("option", { name: /Fabric/ }).click();
    await page.getByRole("button", { name: "Create anchor" }).click();
    const error = page.getByTestId("anchor-error");
    await expect(error).toBeVisible();
    await expect(error).toContainText("501");
    await expect(error).toContainText("not_implemented");
    await expect(anchorRows).toHaveCount(2);
    await expect(page.getByRole("heading", { name: "Custody", level: 1 })).toBeVisible();
  });
});
