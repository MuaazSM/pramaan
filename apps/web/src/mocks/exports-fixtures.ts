import type { components } from "@/api/schema.gen";

type ExportRecord = components["schemas"]["ExportRecord"];
type ExportVerifyResult = components["schemas"]["ExportVerifyResult"];

/**
 * Deterministic fixtures for the signed-export screen (F4 exports). Synthetic, modelled on the
 * real manifest shape in packages/export/pramaan_export/manifest.py — no `Date.now()` and no
 * `Math.random()` anywhere here, so re-running the mock produces identical ids/hashes.
 *
 * MOCK VERIFY CONVENTION (relied on by playwright/f4-exports.spec.ts — keep in sync):
 *   - the uploaded file must start with `EXPORT_MAGIC` (the same ISO-BMFF `ftyp` prefix the
 *     stub backend's placeholder MP4 uses, and that `GET /api/exports/:xid/file` serves here);
 *   - filename contains "tampered"      -> signature_valid: false, source_matches: false
 *   - bytes do NOT start with the magic -> signature_valid: false, source_matches: false
 *   - filename contains "unregistered"  -> signature_valid: true,  source_matches: false
 *     (a genuine signature over a source image that is not registered in any case — the two
 *     facts are independent, so the screen must show them as two separate indicators)
 *   - anything else                      -> signature_valid: true,  source_matches: true
 */
export const EXPORT_MAGIC = new Uint8Array([
  0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0x69, 0x73, 0x6f, 0x6d, 0x00, 0x00, 0x02, 0x00, 0x69, 0x73, 0x6f, 0x6d, 0x69,
  0x73, 0x6f, 0x32,
]);

/** Tiny placeholder MP4 (magic prefix + zero padding). Not a playable video — it is a mock. */
export function buildPlaceholderMp4(): Uint8Array {
  const out = new Uint8Array(EXPORT_MAGIC.length + 512);
  out.set(EXPORT_MAGIC, 0);
  return out;
}

export function startsWithExportMagic(bytes: Uint8Array): boolean {
  if (bytes.length < EXPORT_MAGIC.length) return false;
  return EXPORT_MAGIC.every((b, i) => bytes[i] === b);
}

/** 32-bit FNV-1a over a string. */
function fnv1a(input: string, seed: number): number {
  let h = (0x811c9dc5 ^ seed) >>> 0;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** 64-hex-char, SHA-256-looking digest derived (deterministically) from the input. */
export function fakeSha256(input: string): string {
  let out = "";
  for (let i = 0; i < 8; i++) out += fnv1a(input, i * 0x9e3779b1).toString(16).padStart(8, "0");
  return out;
}

export interface ExportInput {
  recording_id: string | null;
  channel: number | null;
  from_norm_us: number | null;
  to_norm_us: number | null;
}

/** Content-derived export record: identical inputs always produce the identical id + hash. */
export function buildExportRecord(caseId: string, input: ExportInput, examiner: string): ExportRecord {
  const key = JSON.stringify([caseId, input.recording_id, input.channel, input.from_norm_us, input.to_norm_us]);
  const manifestSha = fakeSha256(`manifest|${key}`);
  const xid = `exp_${manifestSha.slice(0, 16)}`;
  // Fixed base instant + a hash-derived offset (whole seconds) instead of the wall clock.
  const createdMs = Date.parse("2026-03-14T09:30:00.000Z") + (fnv1a(key, 7) % 3600) * 1000;
  return {
    id: xid,
    case_id: caseId,
    recording_id: input.recording_id,
    channel: input.channel,
    from_norm_us: input.from_norm_us,
    to_norm_us: input.to_norm_us,
    created_utc: new Date(createdMs).toISOString(),
    examiner,
    file_path: `data/cases/${caseId}/exports/${xid}.mp4`,
    signature_path: `data/cases/${caseId}/exports/${xid}.sig`,
    manifest_sha256: manifestSha,
  };
}

const SOURCE_SHA256 = "a41f09c2b8d3e6710f4c9a2b5e8d1f0c3a6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d";

export function buildVerifyResult(fileName: string, bytes: Uint8Array): ExportVerifyResult {
  const tampered = fileName.toLowerCase().includes("tampered") || !startsWithExportMagic(bytes);
  const unregistered = fileName.toLowerCase().includes("unregistered");
  const manifest: Record<string, unknown> = {
    source_image_id: "ev_hiksim01",
    source_sha256: unregistered ? fakeSha256("unregistered-source") : SOURCE_SHA256,
    channel: 2,
    recording_id: null,
    frame_ids: ["frm_ch2_0001", "frm_ch2_0002", "frm_ch2_0003", "frm_ch2_0004", "frm_ch2_0005", "frm_ch2_0006", "frm_ch2_0007", "frm_ch2_0008"],
    byte_ranges: [{ offset: 8_000_000_000, length: 4_096 }],
    device_time_range_us: { start: 1_773_100_800_000_000, end: 1_773_100_860_000_000 },
    normalised_time_range_us: { from: 1_773_100_800_000_000, to: 1_773_100_860_000_000 },
    examiner: { display_name: "R. Deshmukh", username: "examiner" },
    video_sha256: fakeSha256(`video|${fileName}`),
    tool: { name: "pramaan", version: "0.1.0-mock", step: "export.build_export" },
    export_format_note:
      "ONVIF-style signed export (not conformance-tested against ONVIF-ExportFileFormat-Spec) — see docs/02-BACKEND.md §10.",
  };
  if (tampered) {
    manifest._verification_notes = ["signature does not verify against the examiner public key (mock: tampered or non-export file)"];
    return { signature_valid: false, manifest, source_matches_registered_evidence: false };
  }
  return { signature_valid: true, manifest, source_matches_registered_evidence: !unregistered };
}
