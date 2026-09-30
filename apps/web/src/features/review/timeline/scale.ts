/**
 * Pure timeline scale maths: pixel <-> microsecond mapping, zoom/pan, and adaptive tick
 * generation (days -> hours -> minutes -> seconds -> frames, per docs/04-FRONTEND.md §5.1).
 * Kept dependency-free and canvas-free so it's unit-testable and reusable by draw.ts.
 */
import { US_PER_DAY, US_PER_HOUR, US_PER_MIN, US_PER_S } from "../lib/time";

export interface Viewport {
  /** Visible range, normalised microseconds. */
  startUs: number;
  endUs: number;
  /** CSS pixel width of the drawable area (track body, excludes the header column). */
  widthPx: number;
}

export function usPerPx(viewport: Viewport): number {
  return (viewport.endUs - viewport.startUs) / Math.max(1, viewport.widthPx);
}

export function usToPx(us: number, viewport: Viewport): number {
  return (us - viewport.startUs) / usPerPx(viewport);
}

export function pxToUs(px: number, viewport: Viewport): number {
  return viewport.startUs + px * usPerPx(viewport);
}

/** Zoom by `factor` (>1 = zoom in) holding the microsecond under `anchorPx` fixed. */
export function zoomViewport(viewport: Viewport, factor: number, anchorPx: number, minSpanUs = US_PER_S, maxSpanUs = 32 * US_PER_DAY): Viewport {
  const anchorUs = pxToUs(anchorPx, viewport);
  const span = viewport.endUs - viewport.startUs;
  const nextSpan = Math.min(maxSpanUs, Math.max(minSpanUs, span / factor));
  const ratio = (anchorUs - viewport.startUs) / span;
  const startUs = anchorUs - ratio * nextSpan;
  return { ...viewport, startUs, endUs: startUs + nextSpan };
}

/** Pan by `deltaPx` (positive = content moves right = viewport moves left/earlier). */
export function panViewport(viewport: Viewport, deltaPx: number): Viewport {
  const deltaUs = deltaPx * usPerPx(viewport);
  return { ...viewport, startUs: viewport.startUs - deltaUs, endUs: viewport.endUs - deltaUs };
}

export function clampViewport(viewport: Viewport, boundsStartUs: number, boundsEndUs: number): Viewport {
  const span = viewport.endUs - viewport.startUs;
  if (span >= boundsEndUs - boundsStartUs) return { ...viewport, startUs: boundsStartUs, endUs: boundsEndUs };
  let startUs = viewport.startUs;
  let endUs = viewport.endUs;
  if (startUs < boundsStartUs) {
    startUs = boundsStartUs;
    endUs = startUs + span;
  } else if (endUs > boundsEndUs) {
    endUs = boundsEndUs;
    startUs = endUs - span;
  }
  return { ...viewport, startUs, endUs };
}

export type TickLevel = "day" | "hour" | "minute" | "second" | "frame";

export interface Tick {
  us: number;
  level: TickLevel;
  label: string;
  major: boolean;
}

/** "Nice" step candidates, in microseconds, from coarsest to finest. */
const STEP_CANDIDATES: { stepUs: number; level: TickLevel }[] = [
  { stepUs: US_PER_DAY, level: "day" },
  { stepUs: 12 * US_PER_HOUR, level: "day" },
  { stepUs: 6 * US_PER_HOUR, level: "hour" },
  { stepUs: 3 * US_PER_HOUR, level: "hour" },
  { stepUs: US_PER_HOUR, level: "hour" },
  { stepUs: 30 * US_PER_MIN, level: "minute" },
  { stepUs: 10 * US_PER_MIN, level: "minute" },
  { stepUs: 5 * US_PER_MIN, level: "minute" },
  { stepUs: US_PER_MIN, level: "minute" },
  { stepUs: 30 * US_PER_S, level: "second" },
  { stepUs: 10 * US_PER_S, level: "second" },
  { stepUs: 5 * US_PER_S, level: "second" },
  { stepUs: US_PER_S, level: "second" },
  { stepUs: 500_000, level: "second" },
  { stepUs: 200_000, level: "second" },
  { stepUs: 100_000, level: "frame" },
  { stepUs: 40_000, level: "frame" },
];

const MIN_TICK_PX = 64;

function pad(n: number, w = 2): string {
  return String(n).padStart(w, "0");
}

function labelFor(us: number, level: TickLevel): string {
  const istMs = Math.round(us / 1000) + 5.5 * 3600 * 1000;
  const d = new Date(istMs);
  const y = d.getUTCFullYear();
  const mo = pad(d.getUTCMonth() + 1);
  const da = pad(d.getUTCDate());
  const h = pad(d.getUTCHours());
  const mi = pad(d.getUTCMinutes());
  const s = pad(d.getUTCSeconds());
  const ms = pad(d.getUTCMilliseconds(), 3);
  switch (level) {
    case "day":
      return `${y}-${mo}-${da}`;
    case "hour":
      return `${h}:00`;
    case "minute":
      return `${h}:${mi}`;
    case "second":
      return `${h}:${mi}:${s}`;
    case "frame":
      return `${h}:${mi}:${s}.${ms}`;
  }
}

/** Pick the coarsest step whose on-screen spacing is still >= MIN_TICK_PX, and generate ticks. */
export function computeTicks(viewport: Viewport): Tick[] {
  const span = viewport.endUs - viewport.startUs;
  if (span <= 0 || viewport.widthPx <= 0) return [];
  const pxPerUs = viewport.widthPx / span;
  let chosen = STEP_CANDIDATES[0];
  for (const cand of STEP_CANDIDATES) {
    if (cand.stepUs * pxPerUs >= MIN_TICK_PX) chosen = cand;
    else break;
  }
  const { stepUs, level } = chosen;
  const firstTick = Math.ceil(viewport.startUs / stepUs) * stepUs;
  const ticks: Tick[] = [];
  const majorEvery = level === "frame" ? 5 : 4;
  let i = 0;
  for (let us = firstTick; us <= viewport.endUs; us += stepUs) {
    ticks.push({ us, level, label: labelFor(us, level), major: i % majorEvery === 0 });
    i++;
    if (ticks.length > 2000) break; // safety valve
  }
  return ticks;
}
