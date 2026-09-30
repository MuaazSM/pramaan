import { http, HttpResponse } from "msw";
import type { components } from "@/api/schema.gen";
import { buildExportRecord, buildPlaceholderMp4, buildVerifyResult, type ExportInput } from "./exports-fixtures";

type ExportRecord = components["schemas"]["ExportRecord"];

/**
 * Signed-export (F4 exports) MSW handlers. Own module per this task's ownership, spread into the
 * shared `handlers` array in ./handlers.ts as `...exportsHandlers`.
 *
 * Note: the real OpenAPI contract has no `GET /cases/{cid}/exports` list endpoint, so none is
 * mocked either — the screen keeps a session-scoped list from POST responses only. Records are
 * also remembered here (module-level Map) purely so `GET /exports/:xid/file` can 404 for ids this
 * mock never issued, like the real backend does.
 *
 * Verify convention (tamper vs valid vs unregistered) is documented in ./exports-fixtures.ts.
 */

function currentUsername(): string | null {
  const cookie = typeof document !== "undefined" ? document.cookie : "";
  const match = /pramaan_session=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]) : null;
}

function unauthenticated() {
  return HttpResponse.json(
    { error: { code: "unauthenticated", message: "Sign in required.", details: {} } },
    { status: 401 },
  );
}

const issued = new Map<string, ExportRecord>();

export const exportsHandlers = [
  http.post("/api/cases/:cid/exports", async ({ request, params }) => {
    const username = currentUsername();
    if (!username) return unauthenticated();
    const body = (await request.json().catch(() => ({}))) as Partial<ExportInput>;
    const input: ExportInput = {
      recording_id: body.recording_id ?? null,
      channel: body.channel ?? null,
      from_norm_us: body.from_norm_us ?? null,
      to_norm_us: body.to_norm_us ?? null,
    };
    // Same rule as the real backend (export_store._select_frames): a recording or a channel is required.
    if (input.recording_id == null && input.channel == null) {
      return HttpResponse.json(
        { error: { code: "bad_request", message: "Provide either recording_id, or channel (with an optional time range).", details: {} } },
        { status: 400 },
      );
    }
    const record = buildExportRecord(params.cid as string, input, username);
    issued.set(record.id, record);
    return HttpResponse.json(record, { status: 201 });
  }),

  http.get("/api/exports/:xid/file", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    // Ids are content-derived (`exp_` + 16 hex), so a well-formed id is served even after a page
    // reload wiped `issued`; anything else 404s.
    const xid = params.xid as string;
    if (!issued.has(xid) && !/^exp_[0-9a-f]{16}$/.test(xid)) {
      return HttpResponse.json({ error: { code: "not_found", message: "Export not found.", details: {} } }, { status: 404 });
    }
    return new HttpResponse(buildPlaceholderMp4() as unknown as BodyInit, {
      headers: { "Content-Type": "video/mp4", "Content-Disposition": `attachment; filename="${xid}.mp4"` },
    });
  }),

  http.post("/api/exports/verify", async ({ request }) => {
    if (!currentUsername()) return unauthenticated();
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) {
      return HttpResponse.json(
        { detail: [{ loc: ["body", "file"], msg: "Field required", type: "missing" }] },
        { status: 422 },
      );
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    // Small artificial latency so the loading state is observable (deterministic, not random).
    await new Promise((r) => setTimeout(r, 700));
    return HttpResponse.json(buildVerifyResult(file.name, bytes));
  }),
];
