import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Viewport } from "../timeline/scale";
import { clampViewport, zoomViewport, panViewport } from "../timeline/scale";
import { clampUs, resolveGoToInput, US_PER_HOUR } from "../lib/time";

export type GridLayout = 1 | 4 | 9;
export type ShuttleDirection = -1 | 0 | 1;

export interface RangeSelection {
  startUs: number;
  endUs: number;
}

interface PlayheadState {
  /** Bounds of the whole case timeline (normalised us). Set once timeline data loads. */
  boundsStartUs: number;
  boundsEndUs: number;
  playheadUs: number;
  playing: boolean;
  /** Shuttle speed multiplier while playing; sign gives direction (J/K/L). */
  rate: number;
  viewport: Viewport;
  gridLayout: GridLayout;
  activeChannels: number[];
  rangeSelection: RangeSelection | null;
  inspectorCollapsed: boolean;
  /** Video-grid pane height as a percentage of the split area (top=grid, bottom=timeline). */
  videoGridHeightPct: number;
  /** Mock clip playback fps — used to compute a "frame" step in normalised time. See time-mapping.ts. */
  mockClipFps: number;
  mockClipDurationUs: number;

  setBounds: (startUs: number, endUs: number) => void;
  setPlayhead: (us: number) => void;
  stepFrame: (deltaFrames: number) => void;
  stepSeconds: (deltaSeconds: number) => void;
  setPlaying: (playing: boolean) => void;
  setRate: (rate: number) => void;
  cycleShuttle: (direction: ShuttleDirection) => void;
  setGridLayout: (layout: GridLayout) => void;
  setActiveChannels: (channels: number[]) => void;
  setViewport: (viewport: Viewport) => void;
  zoomAt: (anchorPx: number, factor: number) => void;
  panBy: (deltaPx: number) => void;
  setRangeSelection: (sel: RangeSelection | null) => void;
  toggleInspector: () => void;
  setVideoGridHeightPct: (pct: number) => void;
  jumpTo: (raw: string, frameLookup?: (id: string) => number | null) => boolean;
}

const DEFAULT_VIEWPORT: Viewport = { startUs: 0, endUs: 24 * US_PER_HOUR, widthPx: 1000 };

/**
 * Review workspace playback/timeline UI state — the single source of truth the canvas timeline,
 * the video grid, and (later, F3b) the frame inspector all read/write. Only layout preferences
 * (grid layout, inspector collapsed) persist across sessions; playhead/viewport are session-only.
 */
export const usePlayheadStore = create<PlayheadState>()(
  persist(
    (set, get) => ({
      boundsStartUs: DEFAULT_VIEWPORT.startUs,
      boundsEndUs: DEFAULT_VIEWPORT.endUs,
      playheadUs: DEFAULT_VIEWPORT.startUs,
      playing: false,
      rate: 1,
      viewport: DEFAULT_VIEWPORT,
      gridLayout: 4,
      activeChannels: [1, 2, 3, 4],
      rangeSelection: null,
      inspectorCollapsed: false,
      videoGridHeightPct: 55,
      mockClipFps: 10,
      mockClipDurationUs: 20 * 1_000_000,

      setBounds: (startUs, endUs) =>
        set((s) => ({
          boundsStartUs: startUs,
          boundsEndUs: endUs,
          playheadUs: clampUs(s.playheadUs, startUs, endUs),
          viewport: clampViewport({ ...s.viewport, startUs, endUs }, startUs, endUs),
        })),

      setPlayhead: (us) =>
        set((s) => ({ playheadUs: clampUs(us, s.boundsStartUs, s.boundsEndUs) })),

      stepFrame: (deltaFrames) => {
        const s = get();
        const frameUs = 1_000_000 / s.mockClipFps;
        s.setPlayhead(s.playheadUs + deltaFrames * frameUs);
      },

      stepSeconds: (deltaSeconds) => {
        const s = get();
        s.setPlayhead(s.playheadUs + deltaSeconds * 1_000_000);
      },

      setPlaying: (playing) => set({ playing }),
      setRate: (rate) => set({ rate }),

      cycleShuttle: (direction) => {
        const s = get();
        if (direction === 0) {
          set({ playing: false, rate: 1 });
          return;
        }
        const sameDir = Math.sign(s.rate) === direction && s.playing;
        const magnitudes = [1, 2, 4];
        const currentMagIdx = magnitudes.indexOf(Math.abs(s.rate));
        const nextMag = sameDir ? magnitudes[Math.min(magnitudes.length - 1, (currentMagIdx === -1 ? 0 : currentMagIdx) + 1)] : 1;
        set({ playing: true, rate: direction * nextMag });
      },

      setGridLayout: (gridLayout) => set({ gridLayout }),
      setActiveChannels: (activeChannels) => set({ activeChannels }),

      setViewport: (viewport) => {
        const s = get();
        set({ viewport: clampViewport(viewport, s.boundsStartUs, s.boundsEndUs) });
      },

      zoomAt: (anchorPx, factor) => {
        const s = get();
        set({ viewport: clampViewport(zoomViewport(s.viewport, factor, anchorPx), s.boundsStartUs, s.boundsEndUs) });
      },

      panBy: (deltaPx) => {
        const s = get();
        set({ viewport: clampViewport(panViewport(s.viewport, deltaPx), s.boundsStartUs, s.boundsEndUs) });
      },

      setRangeSelection: (rangeSelection) => set({ rangeSelection }),
      toggleInspector: () => set((s) => ({ inspectorCollapsed: !s.inspectorCollapsed })),
      setVideoGridHeightPct: (pct) => set({ videoGridHeightPct: Math.min(80, Math.max(20, pct)) }),

      jumpTo: (raw, frameLookup) => {
        const s = get();
        const result = resolveGoToInput(raw, s.playheadUs, frameLookup);
        if (!result) return false;
        const us = clampUs(result.us, s.boundsStartUs, s.boundsEndUs);
        set({ playheadUs: us });
        // Bring the playhead into view if it's currently off-screen.
        const v = get().viewport;
        if (us < v.startUs || us > v.endUs) {
          const span = v.endUs - v.startUs;
          const startUs = clampUs(us - span / 2, s.boundsStartUs, s.boundsEndUs - span);
          set({ viewport: clampViewport({ ...v, startUs, endUs: startUs + span }, s.boundsStartUs, s.boundsEndUs) });
        }
        return true;
      },
    }),
    {
      name: "pramaan-review-layout",
      partialize: (s) => ({
        gridLayout: s.gridLayout,
        inspectorCollapsed: s.inspectorCollapsed,
        videoGridHeightPct: s.videoGridHeightPct,
      }),
    },
  ),
);
