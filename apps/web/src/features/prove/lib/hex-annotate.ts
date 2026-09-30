/**
 * Pure functions mapping a `HexView` response (apps/api/openapi.json's `HexView` schema — a byte
 * window + a loose list of `{name, offset, length, ...}` annotations, both stub and real backends
 * produce exactly `vendor_header` / `start_code` / `payload`, see docs/progress/W0.3.md and
 * `apps/api/pramaan_api/real/pipeline_store.py::frame_hex_view`) into the shapes the hex grid,
 * field decoder and sector gutter render. Kept dependency-free and synchronous so it is
 * unit-testable without a browser (docs/04-FRONTEND.md §9: "hex annotation mapping").
 *
 * `offset` on every annotation is *relative to the window* (`HexView.offset` is the window's
 * absolute disk offset) — matching the backend's contract exactly, not something this file
 * invents.
 */

export const BYTES_PER_ROW = 16;
export const SECTOR_SIZE = 512;

export type AnnotationKind = "header" | "start_code" | "payload" | "field";

/** The subset of a `HexView.annotations[i]` entry this feature relies on — every other key on the
 * loose `{[key: string]: unknown}` the schema allows is ignored, not required. */
export interface RawAnnotation {
  name: string;
  offset: number;
  length: number;
}

export interface HexAnnotation extends RawAnnotation {
  kind: AnnotationKind;
  /** Absolute disk offset (window offset + relative offset) — what the sector gutter and the
   * field decoder's "offset" column show, since disk offset is the thing being proved. */
  absoluteStart: number;
  absoluteEnd: number;
}

const KNOWN_KIND: Record<string, AnnotationKind> = {
  vendor_header: "header",
  start_code: "start_code",
  payload: "payload",
};

/** Classify a raw `{name, offset, length}` annotation and resolve it to absolute disk offsets.
 * Unrecognised names (a future backend field) fall back to the generic "field" kind rather than
 * being dropped — the grid must still render every byte the server annotates. */
export function classifyAnnotations(raw: RawAnnotation[], windowOffset: number): HexAnnotation[] {
  return raw
    .map((a) => ({
      ...a,
      kind: KNOWN_KIND[a.name] ?? "field",
      absoluteStart: windowOffset + a.offset,
      absoluteEnd: windowOffset + a.offset + a.length,
    }))
    .sort((a, b) => a.offset - b.offset);
}

/**
 * The annotation covering a given byte offset (relative to the window), or undefined if the byte
 * falls in a gap no annotation claims. When regions overlap, the *narrowest* one wins — the more
 * specific field, matching how ImHex's pattern highlighter resolves nested structures.
 */
export function annotationAtOffset(annotations: HexAnnotation[], relOffset: number): HexAnnotation | undefined {
  let best: HexAnnotation | undefined;
  for (const a of annotations) {
    if (relOffset >= a.offset && relOffset < a.offset + a.length) {
      if (!best || a.length < best.length) best = a;
    }
  }
  return best;
}

export interface HexRow {
  /** Row index within the window (0-based). */
  index: number;
  /** Absolute disk offset of the row's first byte. */
  offset: number;
  bytes: number[];
  /** Disk sector (512-byte) the row's first byte falls in. */
  sector: number;
  /** True for the first row of a new sector — the gutter shows the sector number here. */
  sectorStart: boolean;
}

/** Chunk a byte window into fixed-width rows for the hex grid, each carrying its absolute offset
 * and sector so the grid and the gutter never need to re-derive them per cell. */
export function buildHexRows(bytes: Uint8Array, windowOffset: number, bytesPerRow = BYTES_PER_ROW): HexRow[] {
  const rows: HexRow[] = [];
  for (let i = 0; i < bytes.length; i += bytesPerRow) {
    const offset = windowOffset + i;
    const sector = sectorForOffset(offset);
    const prevSector = i === 0 ? null : sectorForOffset(windowOffset + i - bytesPerRow);
    rows.push({
      index: i / bytesPerRow,
      offset,
      bytes: Array.from(bytes.subarray(i, i + bytesPerRow)),
      sector,
      sectorStart: sector !== prevSector,
    });
  }
  return rows;
}

export function sectorForOffset(absoluteOffset: number, sectorSize = SECTOR_SIZE): number {
  return Math.floor(absoluteOffset / sectorSize);
}

/** Printable-ASCII rendering for the ASCII pane; non-printable bytes render as a middle dot. */
export function byteToAscii(byte: number): string {
  return byte >= 0x20 && byte < 0x7f ? String.fromCharCode(byte) : "·";
}

export function toHexByte(byte: number): string {
  return byte.toString(16).padStart(2, "0");
}

/** Extract the raw bytes an annotation covers, relative to the window. */
export function sliceAnnotation(bytes: Uint8Array, annotation: RawAnnotation): Uint8Array {
  return bytes.subarray(annotation.offset, annotation.offset + annotation.length);
}

export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, toHexByte).join(" ");
}

/** Decode base64 (as returned by `HexView.bytes_b64`) into raw bytes, browser + jsdom safe. */
export function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

export function bytesToHexDigest(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), toHexByte).join("");
}
