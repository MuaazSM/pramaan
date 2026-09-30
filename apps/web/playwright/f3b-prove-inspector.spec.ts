import { test, expect, type Page } from "@playwright/test";

/**
 * Mock e2e for F3b (frame inspector + prove-it hex view) — docs/04-FRONTEND.md §9's "Mock e2e"
 * row, scoped to this task's screen. Runs against the same mock-mode preview build as
 * `shots.spec.ts` (shared `webServer` in playwright.config.ts).
 */

const CASE_ID = "case_cr20260412";
const FRAME_ID = "frm_ch2_0010";
// Must stay in sync with src/mocks/prove-fixtures.ts's DEMO_MISMATCH_FRAME_ID.
const MISMATCH_FRAME_ID = "frm_ch1_0050";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test.describe("F3b mock e2e", () => {
  test("prove-it: hex grid, field decoder, live SHA-256 recompute verifies", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/frames/${FRAME_ID}/prove`);

    await expect(page.getByRole("heading", { name: "Prove it" })).toBeVisible();

    // Hex grid renders the offset gutter (8-digit hex) and at least one sector marker.
    await expect(page.getByText(/^[0-9a-f]{8}$/).first()).toBeVisible();
    await expect(page.getByText(/^sec \d+$/).first()).toBeVisible();

    // Field decoder lists the three annotated regions (scoped to its own panel — "payload" also
    // appears, lowercase, inside the frame-context panel's "Header / payload offset" field).
    const fieldsPanel = page.locator("section", { has: page.getByRole("heading", { name: "Fields" }) });
    await expect(fieldsPanel.getByText("Vendor header")).toBeVisible();
    await expect(fieldsPanel.getByText("Start code")).toBeVisible();
    await expect(fieldsPanel.getByText("Payload", { exact: true })).toBeVisible();

    // Live SHA-256 recompute settles to verified (this frame's mock hash always matches). Both
    // the recompute strip and the inspector's own IntegrityChip render "verified" text, so scope
    // to `.first()` — presence, not uniqueness, is what this asserts.
    await expect(page.getByText("Recomputing SHA-256", { exact: false })).toBeVisible();
    await expect(page.getByText("Verified", { exact: false }).first()).toBeVisible({ timeout: 5_000 });

    // Copy proof — grant clipboard-write on this test's own context rather than editing the
    // shared playwright.config.ts (outside this task's owned paths).
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.getByRole("button", { name: "Copy proof" }).click();
    await expect(page.getByText("Proof copied", { exact: true })).toBeVisible();

    // Frame inspector context panel — clock stack + integrity + Prove it link back to itself.
    await expect(page.getByText("Clock stack")).toBeVisible();
    await expect(page.getByText("Normalised (IST)")).toBeVisible();
    await expect(page.getByText("Provenance")).toBeVisible();
  });

  test("prove-it: mismatch demo frame shows the danger integrity state, not a false verified claim", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/frames/${MISMATCH_FRAME_ID}/prove`);

    await expect(page.getByText("Mismatch", { exact: false }).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/^Verified —/)).toHaveCount(0);
  });

  test("prove-it: widening the before/after window re-fetches a larger byte window", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/frames/${FRAME_ID}/prove`);

    const before = page.getByText(/^\d+B$/).first();
    await expect(before).toHaveText("256B");
    await page.getByRole("button", { name: "Increase before window" }).click();
    await expect(before).toHaveText("512B");
  });
});
