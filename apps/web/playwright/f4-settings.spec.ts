import { test, expect, type Page } from "@playwright/test";

/**
 * F4 mock e2e — settings screen (system health, LLM budget meter, users and roles, keys). Runs
 * against the mock-mode preview build. Needs settings-handlers.ts merged into src/mocks/handlers.ts
 * (GET /api/llm/usage).
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test.describe("F4 settings mock e2e", () => {
  test("health, LLM, users and keys panels render; budget meter is under the caps", async ({ page }) => {
    await login(page);
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();

    // System health (live from the shared HEALTH fixture).
    const health = page.getByTestId("panel-health");
    await expect(health).toContainText("Scanner backend");
    await expect(health).toContainText("python");

    // LLM: the on/off state comes from the shared HEALTH fixture (which other screens may flip),
    // so assert the meter is always shown and that its inactive flag agrees with the badge.
    const llm = page.getByTestId("panel-llm");
    const badge = llm.getByText(/^LLM: (on|off)$/);
    await expect(badge).toBeVisible();
    const isOff = (await badge.textContent()) === "LLM: off";
    const meter = page.getByTestId("budget-meter");
    await expect(meter).toBeVisible();
    await expect(meter).toHaveAttribute("data-inactive", String(isOff));
    await expect(page.getByTestId("budget-spent")).toHaveText("$2.49");
    await expect(meter).toContainText("$60.00 default cap");
    const bar = page.getByRole("progressbar", { name: "Total LLM spend against default cap" });
    const now = Number(await bar.getAttribute("aria-valuenow"));
    expect(now).toBeGreaterThan(0);
    expect(now).toBeLessThan(100);
    // Raw usage rows are listed.
    await expect(llm.getByRole("row")).toHaveCount(9); // header + 8 fixture rows

    // Users and roles: read-only reference, no fake management controls.
    const users = page.getByTestId("panel-users");
    await expect(users).toContainText("read-only");
    await expect(users).toContainText("reviewer");
    await expect(users.getByRole("button")).toHaveCount(0);

    // Keys: read-only reference.
    const keys = page.getByTestId("panel-keys");
    await expect(keys).toContainText("Ed25519");
    await expect(keys).toContainText("read-only");
    await expect(keys.getByRole("button")).toHaveCount(0);
  });
});
