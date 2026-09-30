import { useCallback, useRef } from "react";
import { GripHorizontal } from "lucide-react";
import { usePlayheadStore } from "../store/playhead";

/** Drag handle between the video grid (top) and the timeline (bottom); see docs/04-FRONTEND.md
 * §5.1 "top = video grid (resizable), bottom = timeline (min 220px)". Size persists (store). */
export function SplitHandle({ containerRef }: { containerRef: React.RefObject<HTMLElement | null> }) {
  const setVideoGridHeightPct = usePlayheadStore((s) => s.setVideoGridHeightPct);
  const dragging = useRef(false);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const pct = ((e.clientY - rect.top) / rect.height) * 100;
      setVideoGridHeightPct(pct);
    },
    [containerRef, setVideoGridHeightPct],
  );

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label="Resize video grid and timeline"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onKeyDown={(e) => {
        const step = 3;
        if (e.key === "ArrowUp") usePlayheadStore.getState().setVideoGridHeightPct(usePlayheadStore.getState().videoGridHeightPct - step);
        if (e.key === "ArrowDown") usePlayheadStore.getState().setVideoGridHeightPct(usePlayheadStore.getState().videoGridHeightPct + step);
      }}
      className="focus-ring group flex h-2 shrink-0 cursor-row-resize items-center justify-center bg-panel"
    >
      <GripHorizontal size={14} strokeWidth={1.5} className="text-text-3 group-hover:text-text-2" />
    </div>
  );
}
