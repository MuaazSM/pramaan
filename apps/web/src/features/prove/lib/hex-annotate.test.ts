import { describe, it, expect } from "vitest";
import {
  classifyAnnotations,
  annotationAtOffset,
  buildHexRows,
  sectorForOffset,
  byteToAscii,
  toHexByte,
  sliceAnnotation,
  bytesToHex,
  base64ToBytes,
  BYTES_PER_ROW,
  SECTOR_SIZE,
  type RawAnnotation,
} from "./hex-annotate";
import { decodeStartCode, decodeNalHeader } from "./codec-decode";

// Mirrors apps/api/pramaan_api/fixtures/store.py::frame_hex_view's shape: window starts 224
// bytes before the payload (header_len = 224), a 4-byte start code just before the payload.
const WINDOW_OFFSET = 4096 - 224;
const HEADER_LEN = 224;
const RAW: RawAnnotation[] = [
  { name: "vendor_header", offset: 0, length: HEADER_LEN },
  { name: "start_code", offset: HEADER_LEN - 4, length: 4 },
  { name: "payload", offset: HEADER_LEN, length: 512 },
];

describe("classifyAnnotations", () => {
  it("maps known backend names to their kind and resolves absolute disk offsets", () => {
    const out = classifyAnnotations(RAW, WINDOW_OFFSET);
    expect(out.map((a) => a.kind)).toEqual(["header", "start_code", "payload"]);
    const header = out.find((a) => a.name === "vendor_header")!;
    expect(header.absoluteStart).toBe(WINDOW_OFFSET);
    expect(header.absoluteEnd).toBe(WINDOW_OFFSET + HEADER_LEN);
    const payload = out.find((a) => a.name === "payload")!;
    expect(payload.absoluteStart).toBe(4096);
  });

  it("falls back to the generic 'field' kind for a name it doesn't recognise", () => {
    const out = classifyAnnotations([{ name: "future_field", offset: 0, length: 1 }], 0);
    expect(out[0].kind).toBe("field");
  });

  it("sorts by window offset regardless of input order", () => {
    const shuffled = [RAW[2], RAW[0], RAW[1]];
    const out = classifyAnnotations(shuffled, 0);
    expect(out.map((a) => a.name)).toEqual(["vendor_header", "start_code", "payload"]);
  });
});

describe("annotationAtOffset", () => {
  const annotations = classifyAnnotations(RAW, WINDOW_OFFSET);

  it("resolves a byte inside the header region", () => {
    expect(annotationAtOffset(annotations, 0)?.name).toBe("vendor_header");
    expect(annotationAtOffset(annotations, HEADER_LEN - 5)?.name).toBe("vendor_header");
  });

  it("prefers the narrower, more specific region on overlap (start_code nested in vendor_header)", () => {
    // Byte HEADER_LEN-4..HEADER_LEN-1 is covered by both vendor_header (224 bytes) and
    // start_code (4 bytes) — the field decoder should show the specific one.
    expect(annotationAtOffset(annotations, HEADER_LEN - 4)?.name).toBe("start_code");
    expect(annotationAtOffset(annotations, HEADER_LEN - 1)?.name).toBe("start_code");
  });

  it("resolves the payload region and returns undefined past the end of every annotation", () => {
    expect(annotationAtOffset(annotations, HEADER_LEN)?.name).toBe("payload");
    expect(annotationAtOffset(annotations, HEADER_LEN + 511)?.name).toBe("payload");
    expect(annotationAtOffset(annotations, HEADER_LEN + 512)).toBeUndefined();
  });
});

describe("buildHexRows", () => {
  it("chunks bytes into fixed-width rows with correct absolute offsets", () => {
    const bytes = new Uint8Array(40).map((_, i) => i);
    const rows = buildHexRows(bytes, 1000);
    expect(rows).toHaveLength(3); // 16, 16, 8
    expect(rows[0].offset).toBe(1000);
    expect(rows[1].offset).toBe(1016);
    expect(rows[2].bytes).toHaveLength(8);
    expect(rows[0].bytes[0]).toBe(0);
    expect(rows[1].bytes[0]).toBe(16);
  });

  it("marks the first row of each new sector", () => {
    // Window starts 4 bytes before a sector boundary (512): row 0 offset 508, row 1 offset 524 —
    // the sector boundary (512) falls inside row 0, so row 1 is the first row fully in sector 1.
    const bytes = new Uint8Array(BYTES_PER_ROW * 3);
    const rows = buildHexRows(bytes, SECTOR_SIZE - 4);
    expect(rows[0].sector).toBe(0);
    expect(rows[0].sectorStart).toBe(true); // first row overall always starts a (visible) sector
    expect(rows[1].sector).toBe(1);
    expect(rows[1].sectorStart).toBe(true);
    expect(rows[2].sector).toBe(1);
    expect(rows[2].sectorStart).toBe(false);
  });
});

describe("sectorForOffset", () => {
  it("computes 512-byte sector boundaries", () => {
    expect(sectorForOffset(0)).toBe(0);
    expect(sectorForOffset(511)).toBe(0);
    expect(sectorForOffset(512)).toBe(1);
    expect(sectorForOffset(4096)).toBe(8);
  });
});

describe("byte helpers", () => {
  it("renders printable ASCII and a middle dot for non-printable bytes", () => {
    expect(byteToAscii(0x41)).toBe("A");
    expect(byteToAscii(0x00)).toBe("·");
    expect(byteToAscii(0x7f)).toBe("·");
  });

  it("formats a byte as two-digit lowercase hex", () => {
    expect(toHexByte(0)).toBe("00");
    expect(toHexByte(255)).toBe("ff");
    expect(toHexByte(0x0a)).toBe("0a");
  });

  it("slices exactly the bytes an annotation covers", () => {
    const bytes = new Uint8Array([10, 11, 12, 13, 14]);
    const slice = sliceAnnotation(bytes, { name: "x", offset: 1, length: 3 });
    expect(Array.from(slice)).toEqual([11, 12, 13]);
  });

  it("formats bytes as a space-separated hex string", () => {
    expect(bytesToHex(new Uint8Array([0, 255, 16]))).toBe("00 ff 10");
  });

  it("decodes base64 to the exact original bytes", () => {
    const original = new Uint8Array([0, 1, 2, 250, 251, 252, 255]);
    const b64 = btoa(String.fromCharCode(...original));
    expect(Array.from(base64ToBytes(b64))).toEqual(Array.from(original));
  });
});

describe("decodeStartCode", () => {
  it("recognises the 4-byte Annex-B start code", () => {
    const d = decodeStartCode(new Uint8Array([0, 0, 0, 1]));
    expect(d.isAnnexB).toBe(true);
    expect(d.label).toContain("4-byte");
  });

  it("recognises the 3-byte Annex-B start code", () => {
    const d = decodeStartCode(new Uint8Array([0, 0, 1]));
    expect(d.isAnnexB).toBe(true);
    expect(d.label).toContain("3-byte");
  });

  it("says plainly when bytes don't match the pattern, instead of asserting a false claim", () => {
    const d = decodeStartCode(new Uint8Array([9, 9, 9, 9]));
    expect(d.isAnnexB).toBe(false);
    expect(d.label).toMatch(/does not match/i);
  });
});

describe("decodeNalHeader", () => {
  it("decodes an H.264 1-byte header (SPS, nal_unit_type 7)", () => {
    // nal_ref_idc=3, nal_unit_type=7 -> 0b01100111 = 0x67 (a real H.264 SPS header byte)
    const d = decodeNalHeader(new Uint8Array([0x67]), "h264");
    expect(d?.headerLengthBytes).toBe(1);
    expect(d?.nalUnitType).toBe(7);
    expect(d?.typeName).toBe("SPS");
  });

  it("decodes an H.265 2-byte header", () => {
    // nal_unit_type=32 (VPS) in bits 1-6 of byte 0: (32 << 1) = 0x40
    const d = decodeNalHeader(new Uint8Array([0x40, 0x01]), "h265");
    expect(d?.headerLengthBytes).toBe(2);
    expect(d?.nalUnitType).toBe(32);
    expect(d?.typeName).toBe("VPS");
  });

  it("labels an unrecognised type as reserved/unknown rather than guessing", () => {
    const d = decodeNalHeader(new Uint8Array([0x03]), "h264");
    expect(d?.typeName).toContain("unknown type 3");
  });

  it("returns null when there aren't enough bytes to decode", () => {
    expect(decodeNalHeader(new Uint8Array([]), "h264")).toBeNull();
    expect(decodeNalHeader(new Uint8Array([0x40]), "h265")).toBeNull();
  });
});
