import { test, expect } from "@playwright/test";

/**
 * F3a mock e2e (docs/04-FRONTEND.md §9 / F3a acceptance): "jump to 14:02:37 and step frames."
 * Runs against the mock-mode preview build (see playwright.config.ts's webServer), same as
 * shots.spec.ts. A separate spec file (not shots.spec.ts) since this asserts behaviour, not
 * pixels — mirrors F2's f2-evidence-recordings-findings.spec.ts pattern.
 */

const CASE_ID = "case_cr20260412";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

test("review: jump to 14:02:37 and step frames", async ({ page }) => {
  await login(page);
  await page.goto(`/cases/${CASE_ID}/review`);

  // Wait past the loading skeleton for the real grid (four tiles, each carrying a mono timecode).
  const leaderTile = page.locator('[data-testid="video-tile"][data-channel="1"]');
  await expect(leaderTile).toBeVisible();
  const leaderTimecode = leaderTile.getByText(/IST$/);

  // Jump to 14:02:37 (IST) via the toolbar's "go to timecode" command.
  const goToInput = page.getByLabel("Go to timecode");
  await goToInput.fill("14:02:37");
  await page.getByRole("button", { name: "Go" }).click();

  await expect(leaderTimecode).toHaveText(/14:02:37\.000 IST/);

  // The timeline scrubber's playhead (role=slider) should report the same instant.
  const slider = page.getByRole("slider", { name: "Timeline scrubber" });
  const valueAtJump = await slider.getAttribute("aria-valuenow");
  expect(valueAtJump).not.toBeNull();

  // Step three frames forward (mock clip fps = 10 -> 100ms/frame -> +300ms) via the toolbar
  // button (keyboard focus is on it after the click above, so ArrowRight reaches the global
  // review-shortcut handler rather than a text field).
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");

  await expect(leaderTimecode).toHaveText(/14:02:37\.300 IST/);
  const valueAfterSteps = await slider.getAttribute("aria-valuenow");
  expect(Number(valueAfterSteps)).toBeGreaterThan(Number(valueAtJump));
  expect(Number(valueAfterSteps) - Number(valueAtJump)).toBe(300_000); // 3 frames * 100ms, in microseconds

  // Shift+ArrowLeft steps a whole second back.
  await page.keyboard.press("Shift+ArrowLeft");
  await expect(leaderTimecode).toHaveText(/14:02:36\.300 IST/);

  // J/K/L shuttle: pressing L starts forward playback (rAF-driven; playhead should be strictly
  // greater a moment later), and K stops it.
  const beforePlay = Number(await slider.getAttribute("aria-valuenow"));
  await page.keyboard.press("l");
  await page.waitForTimeout(250);
  await page.keyboard.press("k");
  const afterPlay = Number(await slider.getAttribute("aria-valuenow"));
  expect(afterPlay).toBeGreaterThan(beforePlay);

  // Grid layout switch: single-up shows one tile.
  await page.getByRole("button", { name: "Single grid" }).click();
  await expect(page.locator("video")).toHaveCount(1);
  await page.getByRole("button", { name: "Quad grid" }).click();
  await expect(page.locator("video")).toHaveCount(4);
});
