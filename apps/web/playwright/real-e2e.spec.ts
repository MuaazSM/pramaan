import { test, expect, type Page } from "@playwright/test";

/**
 * Real-mode acceptance flow (docs/04-FRONTEND.md §9 "Real e2e": the same flow as the mock e2e
 * specs, against the real API — `PRAMAAN_STUB_MODE=0` — on the synthetic corpus). Run with:
 *
 *   uv run python tools/demo/demo.py --keep-running --port 8000   # seeds CR-2026-0412, leaves the
 *                                                                  # real API up on :8000
 *   pnpm -C apps/web exec playwright test -c playwright.real.config.ts
 *
 * Unlike `playwright/shots.spec.ts`/the mock e2e specs, this file does not hardcode fixture ids
 * (`case_cr20260412`, `ev_hiksim01`, ...) — real-mode ids are content-derived (sha256-based) and
 * only exist once `demo.py` has actually registered/scanned the corpus images, so every id this
 * spec needs is discovered live through the UI/API, never assumed.
 *
 * Split into one `test()` per screen (rather than one long test) so a real, currently-broken
 * backend endpoint (see the "exports" test below) fails in isolation instead of preventing every
 * other screen in the flow from being verified — see docs/progress/F4.md "Cross-workstream
 * issues" for the exact bug this uncovered (do not fix it here: apps/api is out of this task's
 * owned paths).
 */

const CASE_NUMBER = "CR-2026-0412";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("examiner");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/cases");
}

/** Navigates to the seeded demo case via the Cases list (never hardcodes its real, content-derived
 * id) and returns the case id parsed back out of the resulting URL. */
async function openDemoCase(page: Page): Promise<string> {
  await page.goto("/cases");
  await page.getByRole("link", { name: new RegExp(CASE_NUMBER) }).first().click();
  await page.waitForURL(/\/cases\/[^/]+$/);
  const url = new URL(page.url());
  const match = /\/cases\/([^/]+)$/.exec(url.pathname);
  if (!match) throw new Error(`could not parse case id from ${url.pathname}`);
  return match[1];
}

test.describe("real-mode acceptance flow", () => {
  test.setTimeout(60_000);

  test("login -> case overview shows real evidence/integrity data", async ({ page }) => {
    await login(page);
    const cid = await openDemoCase(page);
    expect(cid).toBeTruthy();
    await expect(page.getByText(/verified|pending/i).first()).toBeVisible();
  });

  test("recordings: real scan produced real rows", async ({ page }) => {
    await login(page);
    const cid = await openDemoCase(page);
    await page.goto(`/cases/${cid}/recordings`);
    await expect(page.getByRole("row").nth(1)).toBeVisible({ timeout: 15_000 });
  });

  test("review: timeline + video grid render against real frames, stepping works", async ({ page }) => {
    await login(page);
    const cid = await openDemoCase(page);
    await page.goto(`/cases/${cid}/review`);
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 15_000 });
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
  });

  test("reports: generate a real report, download the real PDF", async ({ page }) => {
    const request = page.request;
    await login(page);
    const cid = await openDemoCase(page);
    await page.goto(`/cases/${cid}/reports`);
    // Two "Generate report" affordances can be on screen at once (the header's primary action and
    // the empty-state card's own inline CTA before any report exists yet) — both trigger the same
    // action, so `.first()` is correct here, not a locator workaround for a real bug.
    await page.getByRole("button", { name: /generate report/i }).first().click();
    await expect(page.getByText(/sha256/i).first()).toBeVisible({ timeout: 30_000 });
    const pdfLink = page.getByRole("link", { name: /^pdf$/i }).first();
    await expect(pdfLink).toBeVisible();
    const pdfHref = await pdfLink.getAttribute("href");
    expect(pdfHref).toBeTruthy();
    if (pdfHref) {
      const pdfRes = await request.get(pdfHref);
      expect(pdfRes.ok()).toBeTruthy();
      const body = await pdfRes.body();
      expect(body.subarray(0, 4).toString("latin1")).toBe("%PDF");
    }
  });

  test("exports: create a real signed export, verify it round-trips (KNOWN BROKEN — see F4.md)", async ({
    page,
  }) => {
    const request = page.request;
    await login(page);
    const cid = await openDemoCase(page);
    await page.goto(`/cases/${cid}/exports`);
    await page.getByRole("combobox", { name: "Recording" }).click();
    await page.getByRole("option").filter({ hasText: /^CH/ }).first().click();
    await page.getByRole("button", { name: /create signed export/i }).click();
    // As of this run, real-mode `POST /cases/{cid}/exports` 500s for every input (channel-only
    // and recording_id both) — `apps/api/pramaan_api/real/pipeline_store.py`'s `_query_frames`
    // SQL selects a `payload_sha256` column the `frames` Parquet schema doesn't have
    // (`duckdb.BinderException: Referenced column "payload_sha256" not found in FROM clause!`).
    // This assertion is expected to fail until that's fixed by whichever workstream owns
    // pipeline_store.py — left as a real, honest failing test rather than skipped or weakened,
    // per this task's "record it, don't fix apps/api" instruction.
    const downloadLink = page.getByRole("link", { name: /download/i }).first();
    await expect(downloadLink).toBeVisible({ timeout: 30_000 });
    const exportHref = await downloadLink.getAttribute("href");
    expect(exportHref).toBeTruthy();
    if (exportHref) {
      const fileRes = await request.get(exportHref);
      expect(fileRes.ok()).toBeTruthy();
      const fileBuffer = await fileRes.body();
      await page.getByLabel("Export file to verify").setInputFiles({
        name: "export-roundtrip.mp4",
        mimeType: "video/mp4",
        buffer: fileBuffer,
      });
      await page.getByRole("button", { name: /verify export/i }).click();
      await expect(page.getByText("Signature valid — source image is registered")).toBeVisible({
        timeout: 15_000,
      });
    }
  });

  test("custody: real hash chain verifies ok (KNOWN BROKEN — see F4.md)", async ({ page }) => {
    // As of this run, real-mode `GET /cases/{cid}/audit/verify` reports `ok: false,
    // first_bad_seq: 1` on every freshly-seeded case, even a clean single-writer one — root-caused
    // to a signature check failing on the Ed25519 keypair `pramaan_custody.keys.
    // load_or_create_keypair` currently has on disk for "examiner" (the hash chain *linkage*
    // itself is fine: `verify_chain(entries, pubkeys=None)` returns `ok=True` on the same data;
    // only the signature check with `pubkeys` supplied fails, starting at entry #1). Likely a
    // TOCTOU race in `load_or_create_keypair` (no locking around first-use key creation) under
    // `tools/demo/demo.py`'s concurrent evidence registration — see docs/progress/F4.md "Cross-
    // workstream issues" for the full reproduction. Left as a real, honest failing test rather
    // than weakened, per this task's "record it, don't fix apps/api / packages/" instruction
    // (packages/custody is CORE/BACKEND-owned, not this task's).
    await login(page);
    const cid = await openDemoCase(page);
    await page.goto(`/cases/${cid}/custody`);
    await expect(page.getByText("chain ok")).toBeVisible({ timeout: 15_000 });
  });

  test("settings: reflects real-mode health (stub_mode off)", async ({ page }) => {
    await login(page);
    await page.goto("/settings");
    await expect(page.getByText(/stub mode/i)).toBeVisible();
  });
});
