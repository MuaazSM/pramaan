import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { PlaySquare } from "lucide-react";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { ReviewToolbar } from "./components/review-toolbar";
import { InspectorSlot } from "./components/inspector-slot";
import { SplitHandle } from "./components/split-handle";
import { VideoGrid } from "./players/video-grid";
import { useReviewShortcuts } from "./players/use-review-shortcuts";
import { TimelineCanvas } from "./timeline/timeline-canvas";
import type { ChannelTimeline, TimelineMarker } from "./timeline/draw";
import { usePlayheadStore } from "./store/playhead";
import { buildFrameIndex } from "./lib/frame-index";

/**
 * Review workspace body (docs/04-FRONTEND.md §5.1): video grid (top, resizable) + timeline
 * (bottom, canvas) + frame-inspector slot (right, F3b mounts there). Mounted by the
 * `/cases/$cid/review` route, which owns the ScreenShell/breadcrumb/custody-seal chrome.
 */
export function ReviewWorkspace({ caseId }: { caseId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const goToInputRef = useRef<HTMLInputElement>(null);
  useReviewShortcuts(goToInputRef);

  const videoGridHeightPct = usePlayheadStore((s) => s.videoGridHeightPct);
  const setBounds = usePlayheadStore((s) => s.setBounds);
  const boundsStartUs = usePlayheadStore((s) => s.boundsStartUs);
  const boundsEndUs = usePlayheadStore((s) => s.boundsEndUs);

  const timelineQuery = useQuery({
    queryKey: ["review-timeline", caseId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/timeline", { params: { path: { cid: caseId } } });
      if (error || !data) throw errorFromResponse(response, "the timeline could not be loaded");
      return data;
    },
  });

  const framesQuery = useQuery({
    queryKey: ["review-frames", caseId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/frames", { params: { path: { cid: caseId } } });
      if (error) throw errorFromResponse(response, "frames could not be loaded");
      return data ?? [];
    },
  });

  // openapi-typescript renders the schema's `prefixItems` tuples (coverage/deleted/motion) as
  // loose `(number | string)[][]` rather than true positional tuples, so we adapt to the exact
  // tuple shape draw.ts/scale.ts expect once, here, at the query boundary — see draw.ts's comment.
  const channels = (timelineQuery.data?.channels ?? []) as unknown as ChannelTimeline[];
  const markers = (timelineQuery.data?.markers ?? []) as unknown as TimelineMarker[];
  const frameIndex = buildFrameIndex(framesQuery.data ?? []);

  useEffect(() => {
    if (channels.length === 0) return;
    let start = Infinity;
    let end = -Infinity;
    for (const ch of channels) {
      for (const [s, e] of ch.coverage) {
        start = Math.min(start, s);
        end = Math.max(end, e);
      }
    }
    if (Number.isFinite(start) && Number.isFinite(end)) setBounds(start, end);
    // Only recompute bounds when the channel dataset identity changes (query refetch), not on
    // every playhead/viewport update these bounds themselves don't depend on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timelineQuery.data]);

  if (timelineQuery.isLoading || framesQuery.isLoading) {
    return (
      <div className="flex h-full flex-col gap-1.5 p-3">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-[45%] w-full" />
        <Skeleton className="h-[45%] w-full" />
      </div>
    );
  }

  if (timelineQuery.isError || framesQuery.isError) {
    const failed = timelineQuery.isError ? timelineQuery : framesQuery;
    return (
      <div className="flex h-full items-center justify-center">
        <QueryErrorState error={failed.error} subject="the review timeline" onRetry={() => void failed.refetch()} />
      </div>
    );
  }

  if (channels.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
        <PlaySquare size={22} strokeWidth={1.5} className="text-text-3" />
        <div>
          <p className="text-base font-medium text-text">No timeline yet</p>
          <p className="mt-1 text-sm text-text-2">Run a scan on this case's evidence to build the timeline.</p>
        </div>
      </div>
    );
  }

  const channelNumbers = channels.map((c) => c.channel);

  return (
    <div className="flex h-full min-h-0">
      <div ref={containerRef} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <ReviewToolbar goToInputRef={goToInputRef} frameIndex={frameIndex} channelNumbers={channelNumbers} />
        {/*
          Split panes use flex-grow ratios with flex-basis: 0 (not `height: X%`) on purpose:
          this flex column's own height is itself established via `flex-1`/`h-full` from its
          ancestors, and CSS percentage heights only resolve against a containing block whose
          height was set *explicitly* (not derived from flex-grow) — with `height: X%` here both
          panes silently fell back to `height: auto` (collapsed to their video/canvas intrinsic
          content size, leaving a large blank gap below). flex-grow distribution doesn't have
          that limitation: it's computed directly from the flex container's resolved main size.
        */}
        <div style={{ flexGrow: videoGridHeightPct, flexBasis: 0 }} className="min-h-0 bg-canvas">
          <VideoGrid channels={channels} boundsStartUs={boundsStartUs} boundsEndUs={boundsEndUs} />
        </div>
        <SplitHandle containerRef={containerRef} />
        <div style={{ flexGrow: 100 - videoGridHeightPct, flexBasis: 0, minHeight: 220 }} className="flex min-h-0">
          <TimelineCanvas channels={channels} markers={markers} />
        </div>
      </div>
      <InspectorSlot caseId={caseId} frames={framesQuery.data ?? []} />
    </div>
  );
}
