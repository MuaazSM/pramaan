import { useEffect, useRef } from "react";
import { VideoOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatTimecode } from "@/lib/format";
import { SOURCE_PLAIN_LABEL, SOURCE_EXPLANATION, GLOSSARY } from "@/lib/humanize";
import { usToIso } from "../lib/time";
import { mapUsToClipSeconds, type ClipMapping } from "../lib/clip-mapping";
import type { ChannelTimeline } from "../timeline/draw";

export type CoverageSource = "index" | "carved" | "inferred" | null;

function coverageAt(ch: ChannelTimeline | undefined, us: number): CoverageSource {
  if (!ch) return null;
  for (const [s, e, source] of ch.coverage) {
    if (us >= s && us < e) return source as CoverageSource;
  }
  return null;
}

interface VideoTileProps {
  channel: ChannelTimeline | undefined;
  mapping: ClipMapping | undefined;
  playheadUs: number;
  /** Only the leader tile actually drives playback; followers just track currentTime. */
  leader: boolean;
  videoRef?: (el: HTMLVideoElement | null) => void;
}

/**
 * One video-grid tile: channel tag, mono normalised timecode, source badge, and a "gap" overlay
 * when there's no coverage at the playhead (docs/04-FRONTEND.md §5.1). The <video> itself is a
 * plain, muted, looping element sourced from the deterministic mock clip for this channel; see
 * clip-mapping.ts for how the case-timeline playhead maps onto the short clip's real duration.
 */
export function VideoTile({ channel, mapping, playheadUs, leader, videoRef }: VideoTileProps) {
  const localRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const video = localRef.current;
    if (!video || !mapping) return;
    const target = mapUsToClipSeconds(playheadUs, mapping);
    if (Math.abs(video.currentTime - target) > 1 / 30) {
      video.currentTime = target;
    }
  }, [playheadUs, mapping]);

  const source = coverageAt(channel, playheadUs);
  const gap = source == null;

  return (
    <div
      data-testid="video-tile"
      data-channel={channel?.channel}
      className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-[var(--radius-card)] border border-line bg-[color-mix(in_oklab,black_70%,var(--ink-900))]"
    >
      <div className="relative min-h-0 flex-1">
        {mapping ? (
          <video
            ref={(el) => {
              localRef.current = el;
              videoRef?.(el);
            }}
            src={mapping.url}
            muted
            playsInline
            preload="auto"
            className={cn("size-full object-contain", gap && "opacity-30")}
          />
        ) : (
          <div className="flex size-full items-center justify-center text-text-3">
            <VideoOff size={20} strokeWidth={1.5} />
          </div>
        )}
        {gap && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-[color-mix(in_oklab,black_55%,transparent)]">
            <VideoOff size={18} strokeWidth={1.5} className="text-text-3" />
            <span className="text-label font-medium text-text-2">No footage at this time</span>
          </div>
        )}
        <div
          className="absolute left-0 top-0 h-full w-[3px]"
          style={{ background: channel ? `var(--${channel.color_token})` : "transparent" }}
          aria-hidden
        />
        {leader && (
          <span
            className="absolute right-2 top-2 rounded-full border border-[var(--brand-400)] bg-[var(--ink-950)] px-1.5 py-0.5 text-caption font-medium text-[var(--brand-300)]"
            title={GLOSSARY.leader}
          >
            Leader
          </span>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 bg-panel px-2 py-1">
        <span className="truncate text-label font-medium text-text">{channel?.label ?? "No channel"}</span>
        <div className="flex shrink-0 items-center gap-1.5">
          {source && (
            <span
              className={cn(
                "rounded-full px-1.5 py-0.5 text-caption font-medium",
                source === "index" && "bg-[var(--ok-tint)] text-ok",
                source === "carved" && "bg-[var(--recovered-tint)] text-recovered",
                source === "inferred" && "bg-[color-mix(in_oklab,var(--inferred)_14%,transparent)] text-inferred",
              )}
              title={SOURCE_EXPLANATION[source]}
            >
              {SOURCE_PLAIN_LABEL[source] ?? source}
            </span>
          )}
          <span className="font-data text-caption tabular-nums text-text-2">{formatTimecode(usToIso(playheadUs))}</span>
        </div>
      </div>
    </div>
  );
}
