import type { components } from "@/api/schema.gen";
import { AUDIT_BY_CASE, DEMO_CASE } from "./fixtures";

type Anchor = components["schemas"]["Anchor"];

/**
 * Deterministic 64-hex-char digest-looking string derived from a seed via FNV-1a. Display-only
 * stand-in for a Merkle root / signature in mock mode — NOT a real hash and never used to verify
 * anything (no Date.now()/Math.random(), so screenshots stay byte-stable).
 */
export function fakeHex(seed: string, chars = 64): string {
  let out = "";
  let round = 0;
  while (out.length < chars) {
    let h = 0x811c9dc5 ^ round;
    const s = `${seed}:${round}`;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    out += h.toString(16).padStart(8, "0");
    round++;
  }
  return out.slice(0, chars);
}

export function makeAnchor(caseId: string, n: number, fromSeq: number, toSeq: number, tsUtc: string): Anchor {
  const key = `${caseId}:${n}:${fromSeq}-${toSeq}`;
  return {
    id: `anc_${fakeHex(key, 12)}`,
    case_id: caseId,
    merkle_root: fakeHex(`root:${key}`),
    from_seq: fromSeq,
    to_seq: toSeq,
    ts_utc: tsUtc,
    backend: "local",
    lab_signature: fakeHex(`sig:${key}`, 128),
  };
}

const demoEntries = AUDIT_BY_CASE[DEMO_CASE.id] ?? [];

/** Seeded anchors: one earlier anchor covering seq 1–96 of the demo case's 128-entry chain. */
export const ANCHORS_BY_CASE: Record<string, Anchor[]> = {
  [DEMO_CASE.id]: [makeAnchor(DEMO_CASE.id, 1, 1, 96, demoEntries[95]?.ts_utc ?? "2026-03-14T10:00:00Z")],
};
