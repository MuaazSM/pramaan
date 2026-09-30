import { useEffect, useRef } from "react";
import { VideoTile } from "./video-tile";
import { usePlayheadStore } from "../store/playhead";
import { CLIP_URL_BY_CHANNEL, MOCK_CLIP_DURATION_S } from "@/mocks/review-fixtures";
import type { ChannelTimeline } from "../timeline/draw";
import type { ClipMapping } from "../lib/clip-mapping";
import { cn } from "@/lib/utils";

const GRID_CLASS: Record<1 | 4 | 9, string> = {
  1: "grid-cols-1 grid-rows-1",
  4: "grid-cols-2 grid-rows-2",
  9: "grid-cols-3 grid-rows-3",
};

interface VideoGridProps {
  channels: ChannelTimeline[];
  boundsStartUs: number;
  boundsEndUs: number;
  className?: string;
}

/**
 * 1/4/9 synced video grid (docs/04-FRONTEND.md §5.1). Playback is driven by a single rAF loop
 * here (not native per-<video> playback + a leader/follower split) so every visible tile —
 * including the notional "leader" — advances from the same clock and reverse shuttle (`J`) is
 * trivial; see docs/progress/F3a.md "Decisions" for why this trades a little playback smoothness
 * for exact multi-tile sync and reliable reverse-play, which matters more for a synced forensic
 * review grid than for a single-stream player.
 */
export function VideoGrid({ channels, boundsStartUs, boundsEndUs, className }: VideoGridProps) {
  const gridLayout = usePlayheadStore((s) => s.gridLayout);
  const activeChannels = usePlayheadStore((s) => s.activeChannels);
  const playheadUs = usePlayheadStore((s) => s.playheadUs);
  const playing = usePlayheadStore((s) => s.playing);
  const rate = usePlayheadStore((s) => s.rate);
  const setPlayhead = usePlayheadStore((s) => s.setPlayhead);
  const setPlaying = usePlayheadStore((s) => s.setPlaying);

  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef<number | null>(null);

  useEffect(() => {
    if (!playing || rate === 0) {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      lastTsRef.current = null;
      return;
    }
    const tick = (ts: number) => {
      const last = lastTsRef.current;
      lastTsRef.current = ts;
      if (last != null) {
        const dtS = (ts - last) / 1000;
        const store = usePlayheadStore.getState();
        const next = store.playheadUs + rate * dtS * 1_000_000;
        if (next >= boundsEndUs || next <= boundsStartUs) {
          setPlayhead(Math.min(boundsEndUs, Math.max(boundsStartUs, next)));
          setPlaying(false);
        } else {
          setPlayhead(next);
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      lastTsRef.current = null;
    };
  }, [playing, rate, boundsStartUs, boundsEndUs, setPlayhead, setPlaying]);

  const slots = Math.min(gridLayout, 9);
  const shown = activeChannels.slice(0, slots);
  const byChannel = new Map(channels.map((c) => [c.channel, c]));

  return (
    <div className={cn("grid h-full gap-1.5 p-1.5", GRID_CLASS[gridLayout], className)}>
      {Array.from({ length: slots }, (_, i) => {
        const channelNum = shown[i];
        const ch = channelNum != null ? byChannel.get(channelNum) : undefined;
        const clipUrl = channelNum != null ? CLIP_URL_BY_CHANNEL[channelNum] : undefined;
        const mapping: ClipMapping | undefined = ch && clipUrl
          ? { channel: ch.channel, url: clipUrl, coverageStartUs: boundsStartUs, coverageEndUs: boundsEndUs, clipDurationS: MOCK_CLIP_DURATION_S }
          : undefined;
        return <VideoTile key={channelNum ?? `empty-${i}`} channel={ch} mapping={mapping} playheadUs={playheadUs} leader={i === 0} />;
      })}
    </div>
  );
}
