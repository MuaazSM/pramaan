import { test, expect, type Page } from "@playwright/test";

/**
 * Mock e2e for F5's keyboard shortcut sheet (`?`) — docs/04-FRONTEND.md §1.4 / the F5 task brief.
 * Runs against the same mock-mode preview build as shots.spec.ts (shared `webServer`).
 */

const CASE_ID = "case_cr20260412";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test.describe("F5 shortcut sheet", () => {
  test("? opens the sheet from anywhere, lists shortcuts, closes on Esc", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}`);
    await expect(page.getByRole("heading", { name: "Shopfront burglary, Andheri" })).toBeVisible();

    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);
    await page.keyboard.press("Shift+?");
    const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Global")).toBeVisible();
    await expect(dialog.getByText("Review workspace")).toBeVisible();
    await expect(dialog.getByText("Shuttle backward (press again to speed up)")).toBeVisible();
    await expect(dialog.getByText("Jump to a timecode, IST datetime, or #frame id")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("the topbar button opens it, and ? is ignored while typing in a field", async ({ page }) => {
    await login(page);
    await page.goto("/cases");

    // Typing "?" into the search box must not toggle the sheet.
    await page.getByPlaceholder("Search case number or title").fill("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);
    await page.getByPlaceholder("Search case number or title").fill("");

    await page.getByRole("button", { name: "Keyboard shortcuts" }).click();
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  });

  test("is reachable from the command palette too", async ({ page }) => {
    await login(page);
    await page.goto("/cases");
    await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();
    await page.keyboard.press("Control+k");
    await page.getByPlaceholder(/Search cases, evidence/).fill("keyboard");
    await page.getByText("Keyboard shortcuts").click();
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  });
});
