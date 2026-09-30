/**
 * Prove-it (F3b) mock fixtures — the `/frames/{fid}/hex` and `/frames/{fid}/thumb` byte payloads.
 *
 * Mirrors the real backend's contract (`apps/api/pramaan_api/real/pipeline_store.py::frame_hex_view`,
 * `apps/api/pramaan_api/fixtures/store.py::frame_hex_view`): the window starts `before` bytes
 * ahead of the frame's header (falling back to its payload offset when there's no separate
 * header offset), spans through the header into `after` bytes of payload, and carries exactly
 * three `{name, offset, length}` annotations (`vendor_header`, `start_code`, `payload`) — nothing
 * this feature's decode logic (src/features/prove/lib/) depends on is invented beyond that
 * contract. Deterministic: every byte is derived from the frame id + window bounds via a seeded
 * PRNG, never `Math.random()` (CLAUDE.md rule 5) — same bytes, same screenshot, every run.
 */
import type { components } from "@/api/schema.gen";

type FrameRef = components["schemas"]["FrameRef"];

/** One existing, ordinary frame (CH1, index-sourced) deliberately given a mismatched *stored*
 * hash in the mock hex handler below, purely to give the visual QA loop and the shots gallery a
 * real "mismatch" integrity state to review — see docs/progress/F3b.md "UI QA verdicts". It is
 * not a claim that anything is actually wrong with this frame. */
export const DEMO_MISMATCH_FRAME_ID = "frm_ch1_0050";

function hashSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h >>> 0;
}

/** Deterministic PRNG (mulberry32) — same convention as review-fixtures.ts's copy; kept as its
 * own small local copy rather than importing a non-exported helper from another task's file. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function syntheticBytes(seed: string, length: number): Uint8Array {
  const rng = mulberry32(hashSeed(seed));
  const out = new Uint8Array(length);
  for (let i = 0; i < length; i++) out[i] = Math.floor(rng() * 256);
  return out;
}

export interface FrameHexAnnotation {
  name: string;
  offset: number;
  length: number;
}

export interface FrameHexFixture {
  offset: number;
  bytes: Uint8Array;
  annotations: FrameHexAnnotation[];
}

/** Builds the byte window + annotations for a frame's hex view, matching the real backend's
 * layout exactly (header window starting at `header_offset ?? payload_offset`, minus `before`,
 * through `after` bytes of payload). */
export function buildFrameHexFixture(frame: FrameRef, before: number, after: number): FrameHexFixture {
  const headerStart = frame.header_offset ?? frame.payload_offset;
  const start = Math.max(0, headerStart - before);
  const headerLen = Math.max(0, frame.payload_offset - start);
  const length = headerLen + after;
  const bytes = syntheticBytes(`${frame.frame_id}:${start}:${length}`, length);
  const startCodeOffset = Math.max(headerLen - 4, 0);
  const startCodeLength = Math.min(4, headerLen);
  const annotations: FrameHexAnnotation[] = [
    { name: "vendor_header", offset: 0, length: headerLen },
    { name: "start_code", offset: startCodeOffset, length: startCodeLength },
    { name: "payload", offset: headerLen, length: after },
  ];
  // Plant a real Annex-B start code where the `start_code` field points (00 00 00 01, or the
  // trailing bytes of it if the window is too narrow for the full 4 bytes) — codec-decode.ts
  // decodes this field from the literal bytes (public H.264/H.265 structure, CLAUDE.md rule 7),
  // so the mock bytes must actually contain one, not just synthetic noise the decoder happens to
  // read past.
  const ANNEX_B_START_CODE = [0x00, 0x00, 0x00, 0x01];
  const startCodeBytes = ANNEX_B_START_CODE.slice(4 - startCodeLength);
  bytes.set(startCodeBytes, startCodeOffset);
  return { offset: start, bytes, annotations };
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** Minimal valid 1x1 JPEG — identical bytes to the real API's fixture placeholder
 * (`apps/api/pramaan_api/fixtures/store.py::frame_thumb_bytes`), so the mock and stub-backend
 * thumbnails are byte-identical. A real decoded-keyframe thumbnail is the pipeline's job. */
export const THUMB_JPEG_BYTES = hexToBytes(
  "ffd8ffe000104a46494600010100000100010000ffdb0043000302020202030202030303030406040404040408060605070907080808070808090a0c0a09" +
    "090b090808080c0a0b0b0c0e0e0e0e0e08090d0f0d0e0e0e0c0dffc0000b0800010001030100022200ffc4001f0000010501010101010100000000000000" +
    "0102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1" +
    "f02433627282090a161718191a25262728292a3435363738393a4344454647" +
    "48494a535455565758595a636465666768696a737475767778797a8283848" +
    "5868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b" +
    "9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f" +
    "2f3f4f5f6f7f8f9faffda0008010100003f00fb",
);
