import { ChevronsRight, ScanEye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { usePlayheadStore } from "../store/playhead";

/**
 * Frame inspector slot (docs/04-FRONTEND.md §5.1: "right = inspector, 320px, collapsible").
 *
 * F3a (this task) only reserves and styles the slot; F3b mounts the real inspector here — the
 * clock stack, lineage breadcrumb, integrity chip and Prove-it/Add-to-report/Export-range
 * actions for the frame at the current playhead. To wire it up:
 *
 *   import { usePlayheadStore } from "@/features/review/store/playhead";
 *   const playheadUs = usePlayheadStore((s) => s.playheadUs);
 *   const rangeSelection = usePlayheadStore((s) => s.rangeSelection);
 *   // resolve playheadUs -> nearest FrameRef (per active/leader channel) and render <FrameInspector />
 *   // in place of <InspectorPlaceholder /> below, inside the same collapsible 320px column.
 *
 * `inspectorCollapsed` already persists (see store/playhead.ts) and the collapse toggle button
 * below is real — F3b only needs to replace the placeholder body.
 */
export function InspectorSlot() {
  const collapsed = usePlayheadStore((s) => s.inspectorCollapsed);
  const toggle = usePlayheadStore((s) => s.toggleInspector);

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
        <span className="text-xs font-medium text-text">Frame inspector</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Collapse inspector" onClick={toggle}>
              <ChevronsRight size={15} strokeWidth={1.5} />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">Collapse</TooltipContent>
        </Tooltip>
      </div>
      {/* F3b mounts <FrameInspector /> here: clock stack, lineage breadcrumb, integrity chip,
          Prove it / Add to report / Export range actions for the frame at the playhead. */}
      <InspectorPlaceholder />
    </div>
  );
}

function InspectorPlaceholder() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="flex size-10 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
        <ScanEye size={18} strokeWidth={1.5} className="text-text-3" />
      </div>
      <div>
        <p className="text-[13px] font-medium text-text">Frame inspector</p>
        <p className="mt-1 text-[12px] text-text-2">
          Clock stack, lineage, integrity chip and Prove it — mounted here by the frame-inspector task.
        </p>
      </div>
      <span className="rounded-full border border-line-strong bg-control px-2.5 py-1 text-[11px] text-text-3">
        Reserved slot · built by WEB (F3b)
      </span>
    </div>
  );
}
