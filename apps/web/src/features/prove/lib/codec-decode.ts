/**
 * Honest, byte-driven decoding of the two structures the "prove it" field decoder claims to
 * understand without a vendor-specific field map: the Annex-B start code and the NAL unit header
 * that follows it (H.264/H.265 are public standards — this is not vendor reverse-engineering).
 *
 * CLAUDE.md rule 7 ("honesty about synthetic data") applies here too: these functions decode
 * *whatever bytes they are given* and say so plainly when the bytes don't match the standard
 * pattern (true for this project's fabricated fixture bytes), rather than asserting a fixed,
 * possibly-wrong label. On real evidence, a genuine Annex-B start code decodes correctly.
 */

const H264_NAL_TYPE: Record<number, string> = {
  0: "unspecified",
  1: "coded slice, non-IDR",
  5: "coded slice, IDR",
  6: "SEI",
  7: "SPS",
  8: "PPS",
  9: "access unit delimiter",
  10: "end of sequence",
  11: "end of stream",
  12: "filler data",
};

const H265_NAL_TYPE: Record<number, string> = {
  19: "IDR_W_RADL (keyframe)",
  20: "IDR_N_LP (keyframe)",
  32: "VPS",
  33: "SPS",
  34: "PPS",
  39: "SEI (prefix)",
  40: "SEI (suffix)",
};

export interface StartCodeDecode {
  bytes: string;
  isAnnexB: boolean;
  label: string;
}

/** Annex-B start codes are `00 00 00 01` (4-byte) or `00 00 01` (3-byte). */
export function decodeStartCode(bytes: Uint8Array): StartCodeDecode {
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(" ");
  const isFour = bytes.length >= 4 && bytes[0] === 0 && bytes[1] === 0 && bytes[2] === 0 && bytes[3] === 1;
  const isThree = !isFour && bytes.length >= 3 && bytes[0] === 0 && bytes[1] === 0 && bytes[2] === 1;
  return {
    bytes: hex,
    isAnnexB: isFour || isThree,
    label: isFour
      ? "Annex-B start code (4-byte 00 00 00 01)"
      : isThree
        ? "Annex-B start code (3-byte 00 00 01)"
        : "Does not match the Annex-B start-code pattern in this byte window.",
  };
}

export interface NalHeaderDecode {
  bytes: string;
  headerLengthBytes: 1 | 2;
  nalUnitType: number;
  typeName: string;
}

/** Decode the NAL unit header immediately following the start code. H.264 uses a 1-byte header
 * (forbidden_zero_bit | nal_ref_idc[2] | nal_unit_type[5]); H.265 uses 2 bytes
 * (forbidden_zero_bit | nal_unit_type[6] | layer_id[6] | temporal_id_plus1[3]). */
export function decodeNalHeader(bytes: Uint8Array, codec: "h264" | "h265"): NalHeaderDecode | null {
  if (codec === "h264") {
    if (bytes.length < 1) return null;
    const b0 = bytes[0];
    const nalUnitType = b0 & 0x1f;
    return {
      bytes: b0.toString(16).padStart(2, "0"),
      headerLengthBytes: 1,
      nalUnitType,
      typeName: H264_NAL_TYPE[nalUnitType] ?? `reserved/unknown type ${nalUnitType}`,
    };
  }
  if (bytes.length < 2) return null;
  const b0 = bytes[0];
  const b1 = bytes[1];
  const nalUnitType = (b0 >> 1) & 0x3f;
  return {
    bytes: `${b0.toString(16).padStart(2, "0")} ${b1.toString(16).padStart(2, "0")}`,
    headerLengthBytes: 2,
    nalUnitType,
    typeName: H265_NAL_TYPE[nalUnitType] ?? `reserved/unknown type ${nalUnitType}`,
  };
}
