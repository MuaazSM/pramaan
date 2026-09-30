import { ChevronsRight, ScanEye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { components } from "@/api/schema.gen";
import { FrameInspector } from "@/features/inspector/frame-inspector";
import { usePlayheadStore } from "../store/playhead";
import { nearestFrameId } from "../lib/frame-index";

type FrameRef = components["schemas"]["FrameRef"];

/**
 * Frame inspector slot (docs/04-FRONTEND.md §5.1: "right = inspector, 320px, collapsible").
 *
 * Mounts the F3b `FrameInspector` for the frame nearest the playhead on the leader channel.
 * "Leader" follows `VideoGrid`'s rule exactly: the first entry of `activeChannels` (the grid's
 * slot 0 is the leader tile). `inspectorCollapsed` persists (see store/playhead.ts).
 */
export function InspectorSlot({ caseId, frames }: { caseId: string; frames: FrameRef[] }) {
  const collapsed = usePlayheadStore((s) => s.inspectorCollapsed);
  const toggle = usePlayheadStore((s) => s.toggleInspector);
  const playheadUs = usePlayheadStore((s) => s.playheadUs);
  const leaderChannel = usePlayheadStore((s) => s.activeChannels[0]);
  const frameId = leaderChannel != null ? nearestFrameId(frames, leaderChannel, playheadUs) : null;

  if (collapsed) {
    return (
      <div className="flex w-9 shrink-0 flex-col items-center border-l border-line bg-panel py-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Expand inspector" onClick={toggle}>
              <ScanEye size={15} strokeWidth={1.5} />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">Expand frame inspector</TooltipContent>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className="flex w-[320px] shrink-0 flex-col border-l border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <span className="text-section text-text">Frame inspector</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Collapse inspector" onClick={toggle}>
              <ChevronsRight size={15} strokeWidth={1.5} />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">Collapse</TooltipContent>
        </Tooltip>
      </div>
      {frameId ? <FrameInspector caseId={caseId} frameId={frameId} /> : <InspectorEmpty />}
    </div>
  );
}

function InspectorEmpty() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="flex size-10 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
        <ScanEye size={18} strokeWidth={1.5} className="text-text-3" />
      </div>
      <div>
        <p className="text-base font-medium text-text">No frame at the current playhead yet</p>
        <p className="mt-1 text-sm text-text-2">
          No indexed frame is available on the leader channel. Move the playhead or pick another channel.
        </p>
      </div>
    </div>
  );
}
