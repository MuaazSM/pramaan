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
