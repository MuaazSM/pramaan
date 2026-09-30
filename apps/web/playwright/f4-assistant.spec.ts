import { test, expect, type Page } from "@playwright/test";

/**
 * F4 mock e2e: (1) the "Ask about this case" assistant inside the command palette, (2) the F3b
 * frame inspector now mounted in the review workspace's InspectorSlot. Mock-mode preview build,
 * same webServer as shots.spec.ts. In mock mode the assistant route mirrors the real default
 * (404 llm_disabled); a question containing `__llm_enabled_demo__` returns a deterministic
 * proposal (see src/mocks/assistant-handlers.ts).
 */

const CASE_ID = "case_cr20260412";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

/** Open the palette with the keyboard shortcut once the shell (topbar Search button) is ready —
 * pressing it during the first paint races the palette's keydown listener registration. */
async function openPalette(page: Page) {
  await expect(page.getByRole("button", { name: /Search/ })).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
}

test.describe("F4 assistant panel", () => {
  test("llm_disabled default state, then editable filter chips on the success path", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}`);

    await openPalette(page);
    // Select via keyboard (filter + Enter): mouse clicks on cmdk items are currently swallowed by
    // ui/command.tsx's `data-[disabled]:pointer-events-none`, which matches data-disabled="false".
    await expect(page.getByRole("option", { name: /Ask about this case/ })).toBeVisible();
    await page.getByRole("combobox").fill("Ask about");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Ask about this case" })).toBeVisible();

    // Ordinary question -> calm "not enabled" state, not a crash / generic error.
    const input = page.getByLabel("Question about this case");
    await input.fill("show me deleted footage on channel 3");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const disabled = page.getByTestId("assistant-disabled");
    await expect(disabled).toBeVisible();
    await expect(disabled).toContainText("AI assistant is not enabled");
    await expect(page.getByRole("alert")).toHaveCount(0);

    // Special demo question -> proposed filter as chips + result count.
    await input.fill("deleted carved footage on channel 3 __llm_enabled_demo__");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await expect(page.getByText("AI draft")).toBeVisible();
    const channels = page.getByTestId("filter-chip-channels");
    await expect(channels).toContainText("3");
    await expect(page.getByTestId("filter-chip-source")).toContainText("carved");
    await expect(page.getByTestId("filter-chip-deleted_only")).toContainText("yes");
    await expect(page.getByTestId("filter-chip-from_ist")).toBeVisible();
    await expect(page.getByTestId("assistant-result-count")).toContainText("3 results");
    await expect(page.getByText(/frame_id: frm_ch3_0240/)).toBeVisible();

    // Edit the channels chip locally.
    await page.getByRole("button", { name: "Edit channels" }).click();
    await page.getByLabel("channels value").fill("2, 3");
    await page.getByRole("button", { name: "Apply channels" }).click();
    await expect(channels).toContainText("2, 3");
    await expect(page.getByText(/Edited locally/)).toBeVisible();

    // Invalid edits are rejected inline and leave the chip unchanged.
    await page.getByRole("button", { name: "Edit channels" }).click();
    await page.getByLabel("channels value").fill("abc");
    await page.getByRole("button", { name: "Apply channels" }).click();
    await expect(page.getByRole("alert")).toContainText("whole numbers");
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(channels).toContainText("2, 3");

    // Boolean chip toggles in place; select chip changes value; remove drops the chip.
    await page.getByRole("button", { name: "Toggle deleted only" }).click();
    await expect(page.getByTestId("filter-chip-deleted_only")).toContainText("no");
    await page.getByRole("button", { name: "Edit source" }).click();
    await page.getByLabel("source value").selectOption("inferred");
    await page.getByRole("button", { name: "Apply source" }).click();
    await expect(page.getByTestId("filter-chip-source")).toContainText("inferred");
    await page.getByRole("button", { name: "Remove to (IST) filter" }).click();
    await expect(page.getByTestId("filter-chip-to_ist")).toHaveCount(0);

    // Reset restores the model's proposal.
    await page.getByRole("button", { name: "Reset to proposal" }).click();
    await expect(channels).toContainText(/^\s*channels\s*3\s*$/);

    // Closing and reopening the palette always lands on the command list again.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await openPalette(page);
    await expect(page.getByRole("option", { name: /Case overview/ })).toBeVisible();
  });

  test("entry point is hidden without a case in scope", async ({ page }) => {
    await login(page);
    await openPalette(page);
    await expect(page.getByRole("option", { name: /All cases/ })).toBeVisible();
    await expect(page.getByRole("option", { name: /Ask about this case/ })).toHaveCount(0);
  });
});

test.describe("F4 review inspector mount", () => {
  test("InspectorSlot renders FrameInspector for the frame nearest the leader playhead", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/review`);
    await expect(page.locator('[data-testid="video-tile"][data-channel="1"]')).toBeVisible();

    // Real inspector content, not the old reserved-slot placeholder.
    await expect(page.getByText("Reserved slot")).toHaveCount(0);
    await expect(page.getByText("Clock stack")).toBeVisible();
    await expect(page.getByRole("link", { name: "Prove it" })).toBeVisible();

    // 14:02:37 IST = 08:32:37Z -> nearest 5-minute sampled frame on leader ch1 is index 103
    // (08:35Z, 2m23s away; index 102 at 08:30Z is 2m37s away).
    await page.getByLabel("Go to timecode").fill("14:02:37");
    await page.getByRole("button", { name: "Go" }).click();
    await expect(page.getByAltText("Frame frm_ch1_0103 thumbnail")).toBeAttached();
  });
});
