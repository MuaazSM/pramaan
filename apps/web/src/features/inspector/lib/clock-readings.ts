/**
 * Resolves a frame's four-clock stack (docs/03-AI-TIMELINE.md §4, BRAND.md §8 signature
 * component 5) into the `ClockReading[]` shape `ClockStack` (F1, src/components/signature/)
 * renders. Pure and synchronous so it's usable from both the inspector panel and any future
 * test — not calling the API itself.
 */
import type { components } from "@/api/schema.gen";
import type { ClockReading } from "@/components/signature/clock-stack";
import { formatOffsetLabel } from "@/lib/format";

type FrameRef = components["schemas"]["FrameRef"];
type ClockModel = components["schemas"]["ClockModel"];

function usToIso(us: number): string {
  return new Date(us / 1000).toISOString();
}

/** The piecewise segment covering a device-clock timestamp, per docs/03 §4's algorithm
 * (identical to recordings-screen.tsx's `normalise` — kept in sync deliberately since both
 * apply the same ClockModel to a device-clock microsecond value). */
function segmentOffsetUs(deviceUs: number, clock: ClockModel | undefined): number {
  if (!clock) return 0;
  const seg = clock.segments.find(
    (s) => (s.from_device_us == null || deviceUs >= s.from_device_us) && (s.to_device_us == null || deviceUs < s.to_device_us),
  );
  return seg?.offset_us ?? 0;
}

export interface ClockStackResult {
  readings: ClockReading[];
  chosenKey: ClockReading["key"];
}

/**
 * Builds the four readings for `ClockStack`: frame header, index, OSD (device time + the clock
 * model's median OSD-vs-device offset, when known), normalised IST (device time minus the
 * seizure/time-change segment offset — docs/03 §4 step 5). The normalised value is always the
 * chosen one: it's what every other screen in the app displays as "the" time for a frame.
 */
export function resolveClockStack(frame: FrameRef, clock: ClockModel | undefined): ClockStackResult {
  const headerUs = frame.ts_header_us;
  const indexUs = frame.ts_index_us;
  const deviceUs = headerUs ?? indexUs ?? null;
  const offsetUs = deviceUs != null ? segmentOffsetUs(deviceUs, clock) : 0;
  const osdUs = headerUs != null && clock?.osd_offset_us != null ? headerUs + clock.osd_offset_us : null;

  const readings: ClockReading[] = [
    { key: "header", label: "Frame header", iso: headerUs != null ? usToIso(headerUs) : null, confidence: null },
    { key: "index", label: "Recording index", iso: indexUs != null ? usToIso(indexUs) : null, confidence: null },
    {
      key: "osd",
      label: "On-screen (OCR)",
      iso: osdUs != null ? usToIso(osdUs) : null,
      confidence: null,
      offsetLabel: clock?.osd_offset_us != null && Math.abs(clock.osd_offset_us) > 1_000_000 ? `${formatOffsetLabel(clock.osd_offset_us)} vs device` : undefined,
    },
    {
      key: "normalised",
      label: "Normalised (IST)",
      iso: deviceUs != null ? usToIso(deviceUs - offsetUs) : null,
      confidence: clock?.confidence ?? null,
      offsetLabel: offsetUs !== 0 ? formatOffsetLabel(offsetUs) + " device drift" : undefined,
    },
  ];

  return { readings, chosenKey: "normalised" };
}
