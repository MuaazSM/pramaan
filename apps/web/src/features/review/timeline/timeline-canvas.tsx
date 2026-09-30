import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  drawTimeline,
  HEAD_Y,
  TRACK_GAP,
  computeTrackH,
  totalHeight,
  type ChannelTimeline,
  type TimelineMarker,
} from "./draw";
import { pxToUs, type Viewport } from "./scale";
import { usePlayheadStore } from "../store/playhead";
import { cn } from "@/lib/utils";

interface TimelineCanvasProps {
  channels: ChannelTimeline[];
  markers: TimelineMarker[];
  className?: string;
}

const colorCache = new Map<string, string>();
let cachedThemeAttr: string | null = null;

/** Resolve a `--token` (or `--ch-n`) CSS custom property to a concrete colour string, cached per
 * paint until the theme attribute changes (dark <-> light swap invalidates the cache). */
function resolveColor(token: string): string {
  const theme = document.documentElement.getAttribute("data-theme");
  if (theme !== cachedThemeAttr) {
    colorCache.clear();
    cachedThemeAttr = theme;
  }
  const cached = colorCache.get(token);
  if (cached) return cached;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim() || "magenta";
  colorCache.set(token, value);
  return value;
}

/**
 * Canvas timeline: ruler, per-channel coverage/deleted/motion tracks, log-event markers, and
 * playhead/range-selection overlays (docs/04-FRONTEND.md §5.1). Channel *headers* (colour rule,
 * label, clock-confidence dot) are plain HTML in a left column so they stay crisp text at any
 * zoom and don't cost canvas draw calls; the header column and the canvas share the same
 * per-row vertical rhythm (HEAD_Y / TRACK_H / TRACK_GAP from draw.ts) so they stay pixel-aligned.
 */
export function TimelineCanvas({ channels, markers, className }: TimelineCanvasProps) {
  const outerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [widthPx, setWidthPx] = useState(800);
  const [availableHeightPx, setAvailableHeightPx] = useState(240);
  const drag = useRef<{ mode: "scrub" | "range"; startPx: number } | null>(null);

  const viewport = usePlayheadStore((s) => s.viewport);
  const playheadUs = usePlayheadStore((s) => s.playheadUs);
  const rangeSelection = usePlayheadStore((s) => s.rangeSelection);
  const setPlayhead = usePlayheadStore((s) => s.setPlayhead);
  const zoomAt = usePlayheadStore((s) => s.zoomAt);
  const setRangeSelection = usePlayheadStore((s) => s.setRangeSelection);

  useEffect(() => {
    const bodyEl = bodyRef.current;
    const outerEl = outerRef.current;
    if (!bodyEl || !outerEl) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target === bodyEl) setWidthPx(Math.round(entry.contentRect.width));
        if (entry.target === outerEl) setAvailableHeightPx(Math.round(entry.contentRect.height));
      }
    });
    ro.observe(bodyEl);
    ro.observe(outerEl);
    return () => ro.disconnect();
  }, []);

  // Track (row) height stretches to fill the panel's actual available height rather than
  // leaving a dead gap below a fixed number of fixed-height rows (see computeTrackH's comment).
  const trackH = useMemo(() => computeTrackH(availableHeightPx, channels.length), [availableHeightPx, channels.length]);
  const contentHeightPx = totalHeight(channels.length, trackH);
  const overflows = contentHeightPx > availableHeightPx + 1;

  const activeViewport: Viewport = useMemo(() => ({ ...viewport, widthPx }), [viewport, widthPx]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.style.width = `${widthPx}px`;
    canvas.style.height = `${contentHeightPx}px`;
    canvas.width = Math.round(widthPx * dpr);
    canvas.height = Math.round(contentHeightPx * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawTimeline(ctx, activeViewport, {
      channels,
      markers,
      playheadUs,
      rangeSelection,
      resolveColor,
      trackH,
    });
  });

  const onWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      e.preventDefault();
      const rect = bodyRef.current?.getBoundingClientRect();
      const anchorPx = rect ? e.clientX - rect.left : widthPx / 2;
      const factor = Math.exp(-e.deltaY * 0.0016);
      zoomAt(anchorPx, factor);
    },
    [zoomAt, widthPx],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const rect = bodyRef.current?.getBoundingClientRect();
      if (!rect) return;
      const px = e.clientX - rect.left;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      if (e.shiftKey) {
        const us = pxToUs(px, activeViewport);
        setRangeSelection({ startUs: us, endUs: us });
        drag.current = { mode: "range", startPx: px };
      } else {
        setPlayhead(pxToUs(px, activeViewport));
        drag.current = { mode: "scrub", startPx: px };
      }
    },
    [activeViewport, setPlayhead, setRangeSelection],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!drag.current) return;
      const rect = bodyRef.current?.getBoundingClientRect();
      if (!rect) return;
      const px = e.clientX - rect.left;
      const us = pxToUs(px, activeViewport);
      if (drag.current.mode === "range") {
        const startUs = pxToUs(drag.current.startPx, activeViewport);
        setRangeSelection({ startUs: Math.min(startUs, us), endUs: Math.max(startUs, us) });
      } else {
        setPlayhead(us);
      }
    },
    [activeViewport, setPlayhead, setRangeSelection],
  );

  const onPointerUp = useCallback(() => {
    drag.current = null;
  }, []);

  return (
    <div
      ref={outerRef}
      className={cn("flex min-h-0 flex-1 items-start select-none", overflows && "overflow-y-auto", className)}
    >
      <div className="flex w-[168px] shrink-0 flex-col border-r border-line bg-panel">
        <div style={{ height: HEAD_Y }} className="shrink-0 border-b border-line" aria-hidden />
        {channels.map((ch, i) => (
          <div
            key={ch.channel}
            style={{ height: trackH, marginBottom: i === channels.length - 1 ? 0 : TRACK_GAP }}
            className="flex items-center gap-2 border-b border-line/60 px-2.5"
          >
            <span
              className="h-full w-[3px] shrink-0 rounded-full"
              style={{ background: `var(--${ch.color_token})` }}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-text">{ch.label}</div>
              <div className="flex items-center gap-1 text-[10px] text-text-3">
                <span
                  className={cn("size-1.5 rounded-full", ch.clock.confidence >= 0.9 ? "bg-ok" : "bg-warn")}
                  aria-hidden
                />
                {Math.round(ch.clock.confidence * 100)}% clock
              </div>
            </div>
          </div>
        ))}
      </div>
      <div
        ref={bodyRef}
        className="relative min-w-0 flex-1 cursor-crosshair overflow-hidden"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        role="slider"
        aria-label="Timeline scrubber"
        aria-valuemin={viewport.startUs}
        aria-valuemax={viewport.endUs}
        aria-valuenow={playheadUs}
        tabIndex={0}
      >
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}
