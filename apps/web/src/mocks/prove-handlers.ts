import { http, HttpResponse } from "msw";
import { FRAMES_BY_CASE } from "./review-fixtures";
import { DEMO_MISMATCH_FRAME_ID, THUMB_JPEG_BYTES, buildFrameHexFixture, bytesToBase64 } from "./prove-fixtures";

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

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  // TS's DOM lib types `SubtleCrypto.digest` as `BufferSource` (excludes SharedArrayBuffer-backed
  // views); a plain `Uint8Array` subarray is always ArrayBuffer-backed here, so this cast is safe.
  const digest = await crypto.subtle.digest("SHA-256", bytes as unknown as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Prove-it (F3b) MSW handlers: `GET /frames/{fid}/hex` and `GET /frames/{fid}/thumb`. Kept in
 * their own module per this task's ownership, spread into the shared `handlers` array in
 * ./handlers.ts. Frame *lookup* (`GET /frames/{fid}`) is F3a's `review-handlers.ts` — not
 * duplicated here, only reused (`FRAMES_BY_CASE`) for the frame metadata the hex/thumb payloads
 * are derived from.
 */
export const proveHandlers = [
  http.get("/api/frames/:fid/hex", async ({ request, params }) => {
    if (!currentUsername()) return unauthenticated();
    const fid = params.fid as string;
    const frame = Object.values(FRAMES_BY_CASE)
      .flat()
      .find((f) => f.frame_id === fid);
    if (!frame) {
      return HttpResponse.json({ error: { code: "not_found", message: "Frame not found.", details: {} } }, { status: 404 });
    }
    const u = new URL(request.url);
    const before = Math.min(8192, Math.max(0, Number(u.searchParams.get("before") ?? "256")));
    const after = Math.min(8192, Math.max(0, Number(u.searchParams.get("after") ?? "512")));

    const { offset, bytes, annotations } = buildFrameHexFixture(frame, before, after);
    const payloadAnnotation = annotations.find((a) => a.name === "payload")!;
    const payloadBytes = bytes.subarray(payloadAnnotation.offset, payloadAnnotation.offset + payloadAnnotation.length);
    const recomputed = await sha256Hex(payloadBytes);
    // Every frame's stored hash matches its (freshly recomputed) bytes, except one ordinary
    // frame deliberately mismatched so the danger/mismatch integrity state has a real screen to
    // show up on — see prove-fixtures.ts's DEMO_MISMATCH_FRAME_ID doc comment.
    const stored = fid === DEMO_MISMATCH_FRAME_ID ? `${recomputed.slice(0, -2)}${recomputed.endsWith("00") ? "ff" : "00"}` : recomputed;

    return HttpResponse.json({
      frame_id: fid,
      offset,
      before,
      after,
      bytes_b64: bytesToBase64(bytes),
      annotations,
      payload_sha256_recomputed: recomputed,
      payload_sha256_stored: stored,
      matches: recomputed === stored,
    });
  }),

  http.get("/api/frames/:fid/thumb", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    const fid = params.fid as string;
    const frame = Object.values(FRAMES_BY_CASE)
      .flat()
      .find((f) => f.frame_id === fid);
    if (!frame) {
      return HttpResponse.json({ error: { code: "not_found", message: "Frame not found.", details: {} } }, { status: 404 });
    }
    return new HttpResponse(THUMB_JPEG_BYTES, { headers: { "Content-Type": "image/jpeg" } });
  }),
];
