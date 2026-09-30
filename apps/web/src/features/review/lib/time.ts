/**
 * Time helpers for the review workspace. All wall-clock values inside this feature are
 * "normalised microseconds since the Unix epoch" (matches `ts_norm_us` on TimelineMarker /
 * `*_ts_us` fields across the openapi schema) so the same arithmetic works for the canvas
 * timeline, the video-grid mapping and the "go to timecode" command.
 *
 * Display is always IST (BRAND.md §4): `formatTimecode` in src/lib/format.ts already renders
 * a UTC ISO string in IST, so every user-facing timecode input in this feature is interpreted
 * as IST wall-clock time and converted back to UTC microseconds here.
 */
import { parseTimecodeInput } from "@/lib/format";

export const US_PER_MS = 1_000;
export const US_PER_S = 1_000_000;
export const US_PER_MIN = 60 * US_PER_S;
export const US_PER_HOUR = 3600 * US_PER_S;
export const US_PER_DAY = 24 * US_PER_HOUR;

const IST_OFFSET_US = 5.5 * US_PER_HOUR;

export function isoToUs(iso: string): number {
  return Date.parse(iso) * US_PER_MS;
}

export function usToIso(us: number): string {
  return new Date(Math.round(us / US_PER_MS)).toISOString();
}

/** Midnight UTC of the UTC calendar date that contains `us`. Used to anchor "HH:MM:SS" input. */
export function utcDayStartUs(us: number): number {
  const d = new Date(Math.round(us / US_PER_MS));
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) * US_PER_MS;
}

export interface GoToResult {
  us: number;
  matchedFrameId?: string;
}

/**
 * Resolve a "go to timecode" command (`G` shortcut / toolbar input): `14:02:37` (IST time-of-day,
 * resolved against the day of `anchorUs`), `2026-03-12 14:02` (full IST date-time), or `#frame-id`
 * (resolved via `frameLookup`). Returns null if the input can't be parsed.
 */
export function resolveGoToInput(
  raw: string,
  anchorUs: number,
  frameLookup?: (id: string) => number | null,
): GoToResult | null {
  const parsed = parseTimecodeInput(raw);
  if (!parsed) return null;
  if (parsed.kind === "frame") {
    const us = frameLookup?.(parsed.id);
    if (us == null) return null;
    return { us, matchedFrameId: parsed.id };
  }
  // Full "YYYY-MM-DD HH:MM" inputs carry their own date; bare "HH:MM:SS" anchors to anchorUs's date.
  const hasDate = /^\d{4}-\d{2}-\d{2}/.test(raw.trim());
  const dayStart = hasDate ? isoToUs(`${raw.trim().slice(0, 10)}T00:00:00.000Z`) : utcDayStartUs(anchorUs);
  const istOfDayUs = (parsed.hh * 3600 + parsed.mm * 60 + parsed.ss) * US_PER_S;
  return { us: dayStart + istOfDayUs - IST_OFFSET_US };
}

/** Clamp `us` into `[start, end]`. */
export function clampUs(us: number, start: number, end: number): number {
  return Math.min(end, Math.max(start, us));
}
