import type { components } from "@/api/schema.gen";

type FrameRef = components["schemas"]["FrameRef"];

export interface FrameRefIndex {
  byId: Map<string, number>;
}

/** Build a `frame_id -> ts_header_us` lookup for the `#frame-id` form of the "go to timecode"
 * command (see lib/time.ts's resolveGoToInput). */
export function buildFrameIndex(frames: FrameRef[]): FrameRefIndex {
  const byId = new Map<string, number>();
  for (const f of frames) {
    if (f.ts_header_us != null) byId.set(f.frame_id, f.ts_header_us);
  }
  return { byId };
}

/**
 * Nearest frame on `channel` to `targetUs` (by `ts_header_us`), for the frame inspector slot.
 * Linear scan — fine at review-workspace scale; ties resolve to the earlier frame in array order.
 * Returns `null` when the channel has no frame with a header timestamp.
 */
export function nearestFrameId(frames: FrameRef[], channel: number, targetUs: number): string | null {
  let bestId: string | null = null;
  let bestDelta = Infinity;
  for (const f of frames) {
    if (f.channel !== channel || f.ts_header_us == null) continue;
    const delta = Math.abs(f.ts_header_us - targetUs);
    if (delta < bestDelta) {
      bestDelta = delta;
      bestId = f.frame_id;
    }
  }
  return bestId;
}
