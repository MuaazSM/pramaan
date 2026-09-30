/**
 * Canvas 2D drawing for the review timeline (docs/04-FRONTEND.md §5.1). A pure function of
 * (ctx, model, viewport) — no DOM/React state read here — so it can be unit- and perf-tested
 * against a minimal fake `CanvasRenderingContext2D` (see draw.perf.test.ts) as well as driven
 * from the real `<canvas>` in timeline-canvas.tsx.
 *
 * Layout (top to bottom), all in CSS px (caller applies `ctx.scale(dpr, dpr)` beforehand):
 *   MARKER_ROW_H   log-event markers (small triangles + hairline)
 *   RULER_H        adaptive ticks + labels
 *   per channel:    HEADER_GAP, then TRACK_H (coverage bar / deleted bar / motion strip)
 */
import { usToPx, computeTicks, type Viewport } from "./scale";

// Standalone (not `components["schemas"][...]`) on purpose: openapi-typescript renders the
// OpenAPI `prefixItems` tuples on ChannelTimeline.coverage/deleted/motion as loose
// `(number | string)[][]` rather than true positional tuples, so code here that destructures
// `[start, end, source]` needs the precise shape. `review-workspace.tsx` adapts the generated
// API type to this one at the query boundary (a same-shape cast, documented there).
export interface ChannelTimeline {
  image_id: string;
  channel: number;
  label: string;
  color_token: string;
  coverage: [number, number, "index" | "carved" | "inferred"][];
  deleted: [number, number, string][];
  motion: [number, number][];
  clock: { confidence: number; summary: string };
}

export interface TimelineMarker {
  ts_norm_us: number;
  kind: string;
  log_event_id: string;
  user: string | null;
}

export const MARKER_ROW_H = 18;
export const RULER_H = 22;
export const TRACK_GAP = 6;
// Base (minimum-comfortable) sub-row heights, at the minimum track height (MIN_TRACK_H).
export const COVERAGE_H = 14;
export const DELETED_H = 8;
export const MOTION_H = 6;
export const MIN_TRACK_H = COVERAGE_H + 2 + DELETED_H + 2 + MOTION_H;
export const MAX_TRACK_H = 72;
/** @deprecated kept for callers that haven't moved to a computed track height (e.g. header
 * column defaults) — equals MIN_TRACK_H. */
export const TRACK_H = MIN_TRACK_H;
export const HEAD_Y = MARKER_ROW_H + RULER_H;

/** Pick a track (row) height that stretches to fill the available canvas body height — a
 * timeline with few channels should use the space it's given (DaVinci/Grafana-style dense
 * panels), not leave a dead gap below a fixed-height set of rows. Clamped so a single channel
 * doesn't get an absurdly tall track and many channels don't get an unreadably short one (the
 * container scrolls instead once MIN_TRACK_H no longer fits everyone). */
export function computeTrackH(availableBodyPx: number, channelCount: number): number {
  if (channelCount <= 0) return MIN_TRACK_H;
  const fitted = (availableBodyPx - HEAD_Y - (channelCount - 1) * TRACK_GAP) / channelCount;
  return Math.min(MAX_TRACK_H, Math.max(MIN_TRACK_H, fitted));
}

export function trackTop(index: number, trackH: number = MIN_TRACK_H): number {
  return HEAD_Y + index * (trackH + TRACK_GAP);
}

export function totalHeight(channelCount: number, trackH: number = MIN_TRACK_H): number {
  return HEAD_Y + channelCount * (trackH + TRACK_GAP);
}

/** Minimal subset of CanvasRenderingContext2D this module needs — lets tests use a fake ctx. */
export interface DrawCtx {
  save(): void;
  restore(): void;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  strokeRect(x: number, y: number, w: number, h: number): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
  stroke(): void;
  fill(): void;
  rect(x: number, y: number, w: number, h: number): void;
  clip(): void;
  fillText(text: string, x: number, y: number): void;
  measureText(text: string): { width: number };
  setLineDash(segments: number[]): void;
  fillStyle: string | CanvasGradient | CanvasPattern;
  strokeStyle: string | CanvasGradient | CanvasPattern;
  lineWidth: number;
  font: string;
  textBaseline: CanvasTextBaseline;
  globalAlpha: number;
}

export interface DrawModel {
  channels: ChannelTimeline[];
  markers: TimelineMarker[];
  playheadUs: number | null;
  rangeSelection: { startUs: number; endUs: number } | null;
  /** Resolve a `--ch-n` CSS variable to a concrete colour the fake/real ctx can use. */
  resolveColor: (token: string) => string;
  /** Row height per channel track, in CSS px. Defaults to MIN_TRACK_H (see computeTrackH). */
  trackH?: number;
}

// Minimum gap (px) kept between the right edge of one ruler label and the left edge of the
// next, so labels never collide however wide a particular level's string is (a "day" label
// like "2026-03-12" is much wider than an "hour" label like "14:00", and STEP_CANDIDATES'
// tick spacing only guarantees >= MIN_TICK_PX=64px between *ticks*, not between *labels*).
const LABEL_GAP_PX = 12;

/**
 * Adaptive tick density (docs/04-FRONTEND.md §5.1): `computeTicks` guarantees ticks themselves
 * never crowd below MIN_TICK_PX, but labelling every 4th tick regardless of actual on-screen
 * spacing under-labels wide spans (F5 bug: only ~2 labels visible at the default 24h zoom,
 * where the chosen step's ticks land well short of the 4-tick modulo). Instead, label greedily
 * left-to-right using the label's *measured* pixel width: draw a tick's label whenever it fits
 * without overlapping the previously-drawn label, so denser regions (narrow labels, e.g.
 * "14:00") get more labels than sparse ones (wide labels, e.g. a full date) for the same pixel
 * budget, and a tick is drawn "major" (taller, brighter) exactly when it earns a label.
 */
function drawRuler(ctx: DrawCtx, viewport: Viewport, resolveColor: (t: string) => string): void {
  const ticks = computeTicks(viewport);
  ctx.strokeStyle = resolveColor("--line");
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, MARKER_ROW_H + RULER_H - 0.5);
  ctx.lineTo(viewport.widthPx, MARKER_ROW_H + RULER_H - 0.5);
  ctx.stroke();

  ctx.font = "11px var(--font-mono, monospace)";
  ctx.textBaseline = "middle";

  let nextLabelMinX = -Infinity;
  for (const t of ticks) {
    const x = usToPx(t.us, viewport);
    const labelX = x + 4;
    const labelWidth = ctx.measureText(t.label).width;
    const canLabel = labelX >= nextLabelMinX && labelX + labelWidth + 4 <= viewport.widthPx;
    ctx.strokeStyle = canLabel ? resolveColor("--line-strong") : resolveColor("--line");
    ctx.beginPath();
    ctx.moveTo(x + 0.5, MARKER_ROW_H + RULER_H - (canLabel ? 10 : 5));
    ctx.lineTo(x + 0.5, MARKER_ROW_H + RULER_H);
    ctx.stroke();
    if (canLabel) {
      ctx.fillStyle = resolveColor("--text-2");
      ctx.fillText(t.label, labelX, MARKER_ROW_H + RULER_H / 2 - 4);
      nextLabelMinX = labelX + labelWidth + LABEL_GAP_PX;
    }
  }
}

const MARKER_COLOR: Record<string, string> = {
  hdd_format: "--danger",
  time_change: "--warn",
  export: "--brand-400",
  config_change: "--inferred",
};

function drawMarkers(ctx: DrawCtx, viewport: Viewport, markers: TimelineMarker[], heightPx: number, resolveColor: (t: string) => string): void {
  for (const m of markers) {
    if (m.ts_norm_us < viewport.startUs || m.ts_norm_us > viewport.endUs) continue;
    const x = usToPx(m.ts_norm_us, viewport);
    const color = resolveColor(MARKER_COLOR[m.kind] ?? "--text-3");
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, 2);
    ctx.lineTo(x - 4, MARKER_ROW_H - 3);
    ctx.lineTo(x + 4, MARKER_ROW_H - 3);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x + 0.5, MARKER_ROW_H);
    ctx.lineTo(x + 0.5, heightPx);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

const MIN_SEG_PX = 1;
const HATCH_MIN_PX = 6;

function drawSegment(
  ctx: DrawCtx,
  x0: number,
  x1: number,
  y: number,
  h: number,
  color: string,
  style: "solid" | "hatched" | "dotted",
): void {
  const w = Math.max(MIN_SEG_PX, x1 - x0);
  if (style === "solid") {
    ctx.fillStyle = color;
    ctx.fillRect(x0, y, w, h);
    return;
  }
  if (style === "dotted") {
    ctx.globalAlpha = 0.14;
    ctx.fillStyle = color;
    ctx.fillRect(x0, y, w, h);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 2]);
    ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(0, w - 1), h - 1);
    ctx.setLineDash([]);
    return;
  }
  // hatched (carved): base tint + diagonal lines, skipped below a pixel-width LOD threshold.
  ctx.globalAlpha = 0.28;
  ctx.fillStyle = color;
  ctx.fillRect(x0, y, w, h);
  ctx.globalAlpha = 1;
  if (w >= HATCH_MIN_PX) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x0, y, w, h);
    ctx.clip();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    const step = 5;
    for (let lx = x0 - h; lx < x1 + h; lx += step) {
      ctx.beginPath();
      ctx.moveTo(lx, y + h);
      ctx.lineTo(lx + h, y);
      ctx.stroke();
    }
    ctx.restore();
  }
}

function drawChannel(
  ctx: DrawCtx,
  ch: ChannelTimeline,
  top: number,
  trackH: number,
  viewport: Viewport,
  resolveColor: (t: string) => string,
): void {
  const color = resolveColor(`--${ch.color_token}`);
  const trackW = viewport.widthPx;
  // Scale the three sub-rows a little with the track height (a taller track, from few channels
  // getting more room, reads a bit more comfortably) but cap them — a "thin heat line" motion
  // strip and a legible-but-not-huge coverage bar stay that way even at MAX_TRACK_H, rather than
  // ballooning to fill whatever space a channel count happens to leave. Any leftover height is
  // even top/bottom padding within the row (the "--card" ground fill), not a stretched bar.
  const scale = Math.min(1.5, trackH / MIN_TRACK_H);
  const coverageH = Math.min(22, Math.round(COVERAGE_H * scale));
  const deletedH = Math.min(13, Math.round(DELETED_H * scale));
  const motionH = Math.min(11, Math.max(4, Math.round(MOTION_H * scale)));
  const usedH = coverageH + 2 + deletedH + 2 + motionH;
  const padTop = Math.max(0, Math.round((trackH - usedH) / 2));
  const rowTop = top + padTop;

  // Base "no coverage" ground for the whole row so gaps read as empty, not black.
  ctx.fillStyle = resolveColor("--card");
  ctx.fillRect(0, top, trackW, trackH);

  for (const [s, e, source] of ch.coverage) {
    if (e < viewport.startUs || s > viewport.endUs) continue;
    const x0 = usToPx(Math.max(s, viewport.startUs), viewport);
    const x1 = usToPx(Math.min(e, viewport.endUs), viewport);
    const style = source === "index" ? "solid" : source === "carved" ? "hatched" : "dotted";
    drawSegment(ctx, x0, x1, rowTop, coverageH, color, style);
  }

  const deletedY = rowTop + coverageH + 2;
  const recoveredColor = resolveColor("--recovered");
  for (const [s, e] of ch.deleted) {
    if (e < viewport.startUs || s > viewport.endUs) continue;
    const x0 = usToPx(Math.max(s, viewport.startUs), viewport);
    const x1 = usToPx(Math.min(e, viewport.endUs), viewport);
    ctx.fillStyle = recoveredColor;
    ctx.fillRect(x0, deletedY, Math.max(MIN_SEG_PX, x1 - x0), deletedH);
  }

  const motionY = deletedY + deletedH + 2;
  ctx.fillStyle = resolveColor("--ink-700");
  ctx.fillRect(0, motionY, trackW, motionH);
  ctx.fillStyle = resolveColor("--ok");
  for (const [us, score] of ch.motion) {
    if (us < viewport.startUs || us > viewport.endUs) continue;
    const x = usToPx(us, viewport);
    const h = Math.max(1, Math.round(motionH * Math.min(1, score)));
    ctx.globalAlpha = 0.25 + 0.65 * Math.min(1, score);
    ctx.fillRect(x, motionY + (motionH - h), 2, h);
    ctx.globalAlpha = 1;
  }
}

function drawPlayhead(ctx: DrawCtx, us: number, viewport: Viewport, heightPx: number, resolveColor: (t: string) => string): void {
  if (us < viewport.startUs || us > viewport.endUs) return;
  const x = usToPx(us, viewport);
  ctx.strokeStyle = resolveColor("--brand-400");
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x + 0.5, 0);
  ctx.lineTo(x + 0.5, heightPx);
  ctx.stroke();
  ctx.fillStyle = resolveColor("--brand-400");
  ctx.beginPath();
  ctx.moveTo(x - 4, 0);
  ctx.lineTo(x + 4, 0);
  ctx.lineTo(x, 6);
  ctx.closePath();
  ctx.fill();
}

function drawRangeSelection(ctx: DrawCtx, sel: { startUs: number; endUs: number }, viewport: Viewport, heightPx: number, resolveColor: (t: string) => string): void {
  const x0 = usToPx(Math.max(sel.startUs, viewport.startUs), viewport);
  const x1 = usToPx(Math.min(sel.endUs, viewport.endUs), viewport);
  if (x1 <= x0) return;
  ctx.fillStyle = resolveColor("--brand-500");
  ctx.globalAlpha = 0.14;
  ctx.fillRect(x0, 0, x1 - x0, heightPx);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = resolveColor("--brand-400");
  ctx.lineWidth = 1;
  ctx.strokeRect(x0 + 0.5, 0.5, Math.max(0, x1 - x0 - 1), heightPx - 1);
}

/** Draw one full frame. Caller is responsible for DPR scaling and clearing outside this call. */
export function drawTimeline(ctx: DrawCtx, viewport: Viewport, model: DrawModel): void {
  const trackH = model.trackH ?? MIN_TRACK_H;
  const heightPx = totalHeight(model.channels.length, trackH);
  ctx.clearRect(0, 0, viewport.widthPx, heightPx);
  drawRuler(ctx, viewport, model.resolveColor);
  model.channels.forEach((ch, i) => drawChannel(ctx, ch, trackTop(i, trackH), trackH, viewport, model.resolveColor));
  drawMarkers(ctx, viewport, model.markers, heightPx, model.resolveColor);
  if (model.rangeSelection) drawRangeSelection(ctx, model.rangeSelection, viewport, heightPx, model.resolveColor);
  if (model.playheadUs != null) drawPlayhead(ctx, model.playheadUs, viewport, heightPx, model.resolveColor);
}
