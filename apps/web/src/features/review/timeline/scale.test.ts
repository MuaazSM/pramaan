import { describe, it, expect } from "vitest";
import { usToPx, pxToUs, zoomViewport, panViewport, clampViewport, computeTicks, type Viewport } from "./scale";
import { US_PER_HOUR, US_PER_DAY, US_PER_S } from "../lib/time";

describe("timeline scale maths", () => {
  const vp: Viewport = { startUs: 0, endUs: 10 * US_PER_S, widthPx: 1000 };

  it("usToPx / pxToUs round-trip", () => {
    const us = 4.5 * US_PER_S;
    const px = usToPx(us, vp);
    expect(px).toBeCloseTo(450, 5);
    expect(pxToUs(px, vp)).toBeCloseTo(us, 5);
  });

  it("zoomViewport keeps the anchor microsecond fixed on screen", () => {
    const anchorPx = 300;
    const anchorUsBefore = pxToUs(anchorPx, vp);
    const zoomed = zoomViewport(vp, 2, anchorPx);
    const anchorUsAfter = pxToUs(anchorPx, zoomed);
    expect(anchorUsAfter).toBeCloseTo(anchorUsBefore, 5);
    expect(zoomed.endUs - zoomed.startUs).toBeCloseTo((vp.endUs - vp.startUs) / 2, 5);
  });

  it("zoomViewport respects min/max span bounds", () => {
    const zoomedIn = zoomViewport(vp, 1e9, 500, 1 * US_PER_S);
    expect(zoomedIn.endUs - zoomedIn.startUs).toBeGreaterThanOrEqual(1 * US_PER_S - 1);
    const zoomedOut = zoomViewport(vp, 1e-9, 500, US_PER_S, 5 * US_PER_S);
    expect(zoomedOut.endUs - zoomedOut.startUs).toBeLessThanOrEqual(5 * US_PER_S + 1);
  });

  it("panViewport shifts start/end by the same amount and preserves span", () => {
    const span = vp.endUs - vp.startUs;
    const panned = panViewport(vp, 100); // drag content right by 100px = viewport moves earlier
    expect(panned.endUs - panned.startUs).toBeCloseTo(span, 5);
    expect(panned.startUs).toBeLessThan(vp.startUs);
  });

  it("clampViewport keeps the viewport inside bounds without changing span when it fits", () => {
    const clamped = clampViewport({ ...vp, startUs: -5 * US_PER_S, endUs: 5 * US_PER_S }, 0, 24 * US_PER_HOUR);
    expect(clamped.startUs).toBe(0);
    expect(clamped.endUs - clamped.startUs).toBeCloseTo(10 * US_PER_S, 5);
  });

  it("clampViewport widens to bounds when the span is larger than the bounds", () => {
    const clamped = clampViewport({ startUs: -10 * US_PER_DAY, endUs: 10 * US_PER_DAY, widthPx: 1000 }, 0, US_PER_DAY);
    expect(clamped.startUs).toBe(0);
    expect(clamped.endUs).toBe(US_PER_DAY);
  });

  it("computeTicks picks day-level ticks for a 24h span and second-level for a 10s span", () => {
    const dayTicks = computeTicks({ startUs: 0, endUs: US_PER_DAY, widthPx: 1200 });
    expect(dayTicks.length).toBeGreaterThan(0);
    expect(["day", "hour"]).toContain(dayTicks[0].level);

    const secTicks = computeTicks(vp);
    expect(secTicks.length).toBeGreaterThan(0);
    expect(["second", "frame"]).toContain(secTicks[0].level);
  });

  it("computeTicks never produces sub-64px-spaced ticks (readability floor)", () => {
    const ticks = computeTicks({ startUs: 0, endUs: 60 * US_PER_S, widthPx: 800 });
    for (let i = 1; i < ticks.length; i++) {
      const pxGap = ((ticks[i].us - ticks[i - 1].us) / (60 * US_PER_S)) * 800;
      expect(pxGap).toBeGreaterThanOrEqual(63); // allow 1px rounding slack
    }
  });

  it("computeTicks returns [] for a degenerate viewport", () => {
    expect(computeTicks({ startUs: 100, endUs: 100, widthPx: 500 })).toEqual([]);
    expect(computeTicks({ startUs: 0, endUs: US_PER_S, widthPx: 0 })).toEqual([]);
  });
});
