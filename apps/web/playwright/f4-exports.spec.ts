import { test, expect, type Page } from "@playwright/test";

/**
 * Mock e2e for F4 exports (signed MP4 export + verify-upload). Runs against the mock-mode preview
 * build (shared `webServer` in playwright.config.ts). Requires `exportsHandlers` to be spread into
 * src/mocks/handlers.ts.
 *
 * Verify convention (src/mocks/exports-fixtures.ts): the mock accepts a file as authentic iff its
 * bytes start with the placeholder MP4 magic and its name does not contain "tampered"; a name
 * containing "unregistered" yields a valid signature whose source image is not registered.
 */

const CASE_ID = "case_cr20260412";

// Same ISO-BMFF `ftyp` prefix as EXPORT_MAGIC in src/mocks/exports-fixtures.ts.
const VALID_BYTES = Buffer.concat([
  Buffer.from([0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0x69, 0x73, 0x6f, 0x6d, 0x00, 0x00, 0x02, 0x00, 0x69, 0x73, 0x6f, 0x6d, 0x69, 0x73, 0x6f, 0x32]),
  Buffer.alloc(512),
]);

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

// IST wall-clock strings (the form interprets datetime-local as IST) and their epoch-us values.
const FROM_LOCAL = "2026-03-10T05:30"; // = 2026-03-10T00:00:00Z
const TO_LOCAL = "2026-03-10T05:31";
const FROM_US = Date.parse("2026-03-10T00:00:00Z") * 1000;
const TO_US = Date.parse("2026-03-10T00:01:00Z") * 1000;

test.describe("F4 exports mock e2e", () => {
  test("create an export, see it in the session list, download link works", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/exports`);

    await expect(page.getByRole("heading", { name: "Exports", exact: true })).toBeVisible();
    // Honest empty state + honest list title (no "history" claim).
    await expect(page.getByText("No exports created this session yet")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Exports created this session" })).toBeVisible();
    await expect(page.getByText("ONVIF-style signed export (not conformance-tested)")).toBeVisible();
    // Breadcrumb resolves the case number, not the raw id.
    await expect(page.getByText("CR-2026-0412").first()).toBeVisible();

    // Validation: neither recording nor channel.
    await page.getByRole("button", { name: "Create signed export" }).click();
    await expect(page.getByRole("alert")).toContainText("Choose a recording, or enter a channel");

    await page.getByLabel("Channel", { exact: true }).fill("2");
    await page.getByLabel("From normalised time (IST)").fill(FROM_LOCAL);
    await page.getByLabel("To normalised time (IST)").fill(TO_LOCAL);
    await page.getByRole("button", { name: "Create signed export" }).click();

    const row = page.getByTestId("export-row");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("CH2");
    await expect(row).toContainText("examiner");
    await expect(row.getByText("verified", { exact: true })).toBeVisible();
    await expect(page.getByText("No exports created this session yet")).toHaveCount(0);

    // Download link points at the file endpoint and (through the mock) serves an MP4.
    const link = row.getByRole("link", { name: /Download exp_/ });
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^\/api\/exports\/exp_[0-9a-f]{16}\/file$/);
    const res = await page.evaluate(async (url) => {
      const r = await fetch(url, { credentials: "include" });
      return { status: r.status, type: r.headers.get("content-type"), size: (await r.arrayBuffer()).byteLength };
    }, href!);
    expect(res.status).toBe(200);
    expect(res.type).toBe("video/mp4");
    expect(res.size).toBeGreaterThan(0);

    // The session list survives in-tab navigation (sessionStorage), and the same input is
    // content-addressed to the same id (no duplicate row).
    await page.reload();
    await expect(page.getByTestId("export-row")).toHaveCount(1);
    await page.getByRole("button", { name: "Create signed export" }).click();
    await expect(page.getByTestId("export-row")).toHaveCount(1);
  });

  test("create an export from a recording selected in the dropdown", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/exports`);
    await page.getByRole("combobox", { name: "Recording" }).click();
    await page.getByRole("option", { name: /CH1 rec_001/ }).click();
    // Channel/time are ignored (and disabled) for a whole-recording export.
    await expect(page.getByLabel("Channel", { exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Create signed export" }).click();
    const row = page.getByTestId("export-row");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("rec_001");
    await expect(row).toContainText("whole recording");
  });

  test("verify zone: authentic file, tampered file, and valid-but-unregistered source are distinct states", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/exports`);
    const zone = page.getByTestId("verify-zone");
    const input = page.getByLabel("Export file to verify");
    const verify = zone.getByRole("button", { name: "Verify export" });

    await expect(verify).toBeDisabled();

    // 1) Authentic: signature valid AND source matches.
    await input.setInputFiles({ name: "export-clean.mp4", mimeType: "video/mp4", buffer: VALID_BYTES });
    await expect(zone.getByTestId("verify-file-name")).toHaveText("export-clean.mp4");
    await expect(verify).toBeEnabled();
    await verify.click();
    await expect(zone.getByText("Checking signature and source hash")).toBeVisible();
    const clean = zone.getByTestId("verify-result");
    await expect(clean).toHaveAttribute("data-signature-valid", "true");
    await expect(clean).toHaveAttribute("data-source-matches", "true");
    await expect(clean).toContainText("Signature valid — source image is registered");
    await expect(clean.getByTestId("fact-signature")).toContainText("verified");
    await expect(clean.getByTestId("fact-source")).toContainText("verified");
    await expect(clean).toContainText("source_image_id");
    await expect(clean).toContainText("ev_hiksim01");

    // 2) Tampered: signature invalid -> danger state, never any "verified" claim.
    await input.setInputFiles({ name: "export-tampered.mp4", mimeType: "video/mp4", buffer: VALID_BYTES });
    // Choosing a new file clears the previous verdict until "Verify export" is pressed again.
    await expect(zone.getByTestId("verify-result")).toHaveCount(0);
    await verify.click();
    const bad = zone.getByTestId("verify-result");
    await expect(bad).toHaveAttribute("data-signature-valid", "false");
    await expect(bad).toContainText("Signature invalid — do not rely on this file");
    await expect(bad.getByTestId("fact-signature")).toContainText("mismatch");
    await expect(bad.getByTestId("fact-signature")).not.toContainText("verified");
    await expect(bad.getByTestId("fact-source")).not.toContainText("verified");
    await expect(bad).not.toContainText("Signature valid");
    await expect(bad).toContainText("unauthenticated");

    // 2b) Not an export at all (wrong magic bytes) is also invalid.
    await input.setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("just some text, not an mp4") });
    await verify.click();
    await expect(zone.getByTestId("verify-result")).toHaveAttribute("data-signature-valid", "false");

    // 3) Valid signature, source not registered: two different facts, shown separately.
    await input.setInputFiles({ name: "export-unregistered.mp4", mimeType: "video/mp4", buffer: VALID_BYTES });
    await verify.click();
    const split = zone.getByTestId("verify-result");
    await expect(split).toHaveAttribute("data-signature-valid", "true");
    await expect(split).toHaveAttribute("data-source-matches", "false");
    await expect(split.getByTestId("fact-signature")).toContainText("verified");
    await expect(split.getByTestId("fact-source")).toContainText("mismatch");
    await expect(split).toContainText("source image is not registered here");
  });

  test("verify zone accepts a dropped file (HTML5 drag-and-drop)", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/exports`);
    const zone = page.getByTestId("verify-zone");
    const dataTransfer = await page.evaluateHandle((bytes) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(bytes)], "export-dropped.mp4", { type: "video/mp4" }));
      return dt;
    }, [...VALID_BYTES]);
    const dropTarget = zone.locator("label[for='export-verify-file']");
    await dropTarget.dispatchEvent("dragover", { dataTransfer });
    await dropTarget.dispatchEvent("drop", { dataTransfer });
    await expect(zone.getByTestId("verify-file-name")).toHaveText("export-dropped.mp4");
    await zone.getByRole("button", { name: "Verify export" }).click();
    await expect(zone.getByTestId("verify-result")).toHaveAttribute("data-signature-valid", "true");
  });

  test("search params prefill the form (review-selection deep link)", async ({ page }) => {
    await login(page);
    await page.goto(`/cases/${CASE_ID}/exports?channel=2&from_norm_us=${FROM_US}&to_norm_us=${TO_US}`);
    await expect(page.getByTestId("prefill-hint")).toContainText("Prefilled from review selection");
    await expect(page.getByLabel("Channel", { exact: true })).toHaveValue("2");
    await expect(page.getByLabel("From normalised time (IST)")).toHaveValue(FROM_LOCAL);
    await expect(page.getByLabel("To normalised time (IST)")).toHaveValue(TO_LOCAL);

    // Editing a field drops the "prefilled" claim (it no longer reflects the selection).
    await page.getByLabel("Channel", { exact: true }).fill("3");
    await expect(page.getByTestId("prefill-hint")).toHaveCount(0);

    // No params -> no hint, empty fields; junk params are ignored rather than crashing.
    await page.goto(`/cases/${CASE_ID}/exports?channel=abc`);
    await expect(page.getByTestId("prefill-hint")).toHaveCount(0);
    await expect(page.getByLabel("Channel", { exact: true })).toHaveValue("");
  });
});
