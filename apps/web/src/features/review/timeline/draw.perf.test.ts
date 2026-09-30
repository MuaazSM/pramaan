import { describe, it, expect } from "vitest";
import { drawTimeline, type DrawCtx, type ChannelTimeline, type TimelineMarker } from "./draw";
import type { Viewport } from "./scale";
import { US_PER_HOUR, US_PER_MIN } from "../lib/time";

/**
 * Perf budget (docs/04-FRONTEND.md §7 / F3a acceptance): "Timeline redraw <= 8ms/frame with
 * 8 channels x 24h mock data." `drawTimeline` is a pure function of (ctx, viewport, model) with
 * no DOM/React dependency, so this test exercises it directly against a no-op fake
 * CanvasRenderingContext2D: jsdom's real canvas is an unimplemented stub (no `canvas` npm
 * package installed, per the project's dependency budget), so it cannot rasterise pixels or be
 * timed meaningfully in Vitest. What *is* measured here, honestly: the function's own JS cost
 * (tick generation, segment/marker iteration, coordinate maths, and the volume + shape of the
 * draw calls it issues) — which is the part of "redraw cost" this codebase controls. Actual
 * GPU/CPU rasterisation time is the browser's, not ours, and isn't measurable outside a real
 * browser (a Playwright-based frame-timing test would be the next step if this budget is ever
 * found to not hold in practice).
 */

function makeFakeCtx(): DrawCtx {
  return {
    save() {},
    restore() {},
    clearRect() {},
    fillRect() {},
    strokeRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    closePath() {},
    stroke() {},
    fill() {},
    rect() {},
    clip() {},
    fillText() {},
    setLineDash() {},
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    font: "",
    textBaseline: "middle",
    globalAlpha: 1,
  };
}

// The fake ctx below never rasterises anything, so the *value* of a resolved colour doesn't
// matter for this perf test — only that resolving one is as cheap as it is in the real
// (CSS-custom-property-reading) resolver timeline-canvas.tsx uses. Returning the token name
// itself avoids inventing hex literals a real component would never contain (token lint, see
// docs/04-FRONTEND.md §9 "Tokens").
function resolveColor(token: string): string {
  return token;
}

/** 8 channels x 24h, one motion sample every 30s, a coverage/deleted segment every ~20min. */
function makeSyntheticChannels(channelCount: number, spanUs: number): ChannelTimeline[] {
  const out: ChannelTimeline[] = [];
  for (let ch = 1; ch <= channelCount; ch++) {
    const coverage: ChannelTimeline["coverage"] = [];
    const deleted: ChannelTimeline["deleted"] = [];
    const motion: ChannelTimeline["motion"] = [];
    const segStep = 20 * US_PER_MIN;
    for (let us = 0; us < spanUs; us += segStep) {
      const source = us % (5 * segStep) === 0 ? "carved" : us % (7 * segStep) === 0 ? "inferred" : "index";
      coverage.push([us, us + segStep, source]);
      if (ch === 3 && us > 8 * US_PER_HOUR && us < 12 * US_PER_HOUR) {
        deleted.push([us, us + segStep, "format"]);
      }
    }
    for (let us = 0; us < spanUs; us += 30 * 1_000_000) {
      motion.push([us, (Math.sin(us / 1e7 + ch) + 1) / 2]);
    }
    out.push({
      image_id: "ev_perf",
      channel: ch,
      label: `CH${ch}`,
      color_token: `ch-${((ch - 1) % 8) + 1}`,
      coverage,
      deleted,
      motion,
      clock: { confidence: 0.9, summary: "log-anchored" },
    });
  }
  return out;
}

function makeSyntheticMarkers(spanUs: number): TimelineMarker[] {
  const out: TimelineMarker[] = [];
  for (let us = 0; us < spanUs; us += 3 * US_PER_HOUR) {
    out.push({ ts_norm_us: us, kind: us % (6 * US_PER_HOUR) === 0 ? "time_change" : "config_change", log_event_id: `log_${us}`, user: "admin" });
  }
  return out;
}

describe("timeline draw perf", () => {
  it("draws 8 channels x 24h in <= 8ms/frame (mean over warmed-up iterations)", () => {
    const spanUs = 24 * US_PER_HOUR;
    const channels = makeSyntheticChannels(8, spanUs);
    const markers = makeSyntheticMarkers(spanUs);
    const viewport: Viewport = { startUs: 0, endUs: spanUs, widthPx: 1600 };
    const ctx = makeFakeCtx();
    const model = { channels, markers, playheadUs: spanUs / 3, rangeSelection: { startUs: spanUs / 4, endUs: spanUs / 2 }, resolveColor };

    // Warm up (JIT) before measuring, then take the mean of N timed frames.
    for (let i = 0; i < 10; i++) drawTimeline(ctx, viewport, model);

    const iterations = 60;
    const start = performance.now();
    for (let i = 0; i < iterations; i++) drawTimeline(ctx, viewport, model);
    const elapsed = performance.now() - start;
    const meanMs = elapsed / iterations;

    console.log(`drawTimeline mean: ${meanMs.toFixed(3)}ms/frame over ${iterations} iterations (8ch x 24h)`);
    expect(meanMs).toBeLessThanOrEqual(8);
  });

  it("stays within budget while zoomed in to a dense, fully-hatched region", () => {
    const spanUs = 24 * US_PER_HOUR;
    const channels = makeSyntheticChannels(8, spanUs);
    const markers = makeSyntheticMarkers(spanUs);
    // Zoom to a 30-minute window at 1600px wide: every coverage segment renders at hatch-LOD width.
    const viewport: Viewport = { startUs: 8 * US_PER_HOUR, endUs: 8 * US_PER_HOUR + 30 * US_PER_MIN, widthPx: 1600 };
    const ctx = makeFakeCtx();
    const model = { channels, markers, playheadUs: viewport.startUs + 100, rangeSelection: null, resolveColor };

    for (let i = 0; i < 10; i++) drawTimeline(ctx, viewport, model);
    const iterations = 60;
    const start = performance.now();
    for (let i = 0; i < iterations; i++) drawTimeline(ctx, viewport, model);
    const meanMs = (performance.now() - start) / iterations;

    console.log(`drawTimeline (zoomed, hatched) mean: ${meanMs.toFixed(3)}ms/frame`);
    expect(meanMs).toBeLessThanOrEqual(8);
  });
});
