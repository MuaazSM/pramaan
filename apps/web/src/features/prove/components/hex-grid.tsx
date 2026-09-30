/**
 * ImHex-style hex grid (docs/04-FRONTEND.md §5 route table / references/UI_REFERENCES.md's ImHex
 * row: "offset gutter, byte grid, ASCII pane, pattern highlighting"). Row-virtualised
 * (`@tanstack/react-virtual`, same technique as recordings-screen.tsx) since `before`/`after` can
 * request up to 8192+8192 bytes = 1024 rows.
 */
import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@/lib/utils";
import { annotationAtOffset, buildHexRows, byteToAscii, toHexByte, type HexAnnotation } from "../lib/hex-annotate";

const ROW_HEIGHT = 20;

const KIND_BG: Record<HexAnnotation["kind"], string> = {
  header: "color-mix(in oklab, var(--ch-1) 16%, transparent)",
  start_code: "color-mix(in oklab, var(--ch-6) 26%, transparent)",
  payload: "transparent",
  field: "color-mix(in oklab, var(--ch-8) 20%, transparent)",
};

export function HexGrid({
  bytes,
  windowOffset,
  annotations,
  hoveredName,
  onHover,
  className,
}: {
  bytes: Uint8Array;
  windowOffset: number;
  annotations: HexAnnotation[];
  hoveredName: string | null;
  onHover: (name: string | null) => void;
  className?: string;
}) {
  const parentRef = useRef<HTMLDivElement>(null);
  const rows = buildHexRows(bytes, windowOffset);

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 16,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom = virtualRows.length > 0 ? rowVirtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;

  return (
    <div
      ref={parentRef}
      // A deliberately dark data plane in both themes (same convention as the review workspace's
      // video tiles, players/video-tile.tsx — a fixed dark canvas with theme-aware chrome around
      // it), not `--ink-950` directly: that literal token made this box pure black in light mode
      // too, since it doesn't participate in the light-theme palette swap (caught in iteration 1).
      className={cn(
        "min-h-[420px] flex-1 overflow-auto rounded-[var(--radius-card)] border border-line bg-[color-mix(in_oklab,black_70%,var(--ink-900))]",
        className,
      )}
    >
      <div className="sticky top-0 z-10 flex border-b border-line bg-panel px-3 py-1.5 font-data text-caption text-text-3">
        <span className="w-[104px] shrink-0">Offset</span>
        <span className="w-[calc(16*22px+8px)] shrink-0">Hex</span>
        <span>ASCII</span>
      </div>
      <div style={{ height: paddingTop }} aria-hidden />
      {virtualRows.map((vr) => {
        const row = rows[vr.index];
        return (
          <div
            key={row.offset}
            data-index={vr.index}
            className="flex items-center px-3 font-data text-caption"
            style={{ height: ROW_HEIGHT }}
          >
            <span className={cn("w-[104px] shrink-0 tabular-nums", row.sectorStart ? "text-accent-text" : "text-text-3")}>
              {row.offset.toString(16).padStart(8, "0")}
              {row.sectorStart && <span className="ml-1 text-caption text-text-3">sec {row.sector}</span>}
            </span>
            <span className="flex w-[calc(16*22px+8px)] shrink-0">
              {row.bytes.map((b, i) => {
                const relOffset = row.offset - windowOffset + i;
                const ann = annotationAtOffset(annotations, relOffset);
                const isHovered = ann != null && ann.name === hoveredName;
                return (
                  <span
                    key={i}
                    onMouseEnter={() => onHover(ann?.name ?? null)}
                    onMouseLeave={() => onHover(null)}
                    className={cn(
                      "inline-flex w-[22px] cursor-default justify-center tabular-nums",
                      i === 8 && "ml-1.5",
                      isHovered ? "rounded-sm text-text ring-1 ring-inset ring-[var(--brand-400)]" : "text-text-2",
                    )}
                    style={{ backgroundColor: ann && !isHovered ? KIND_BG[ann.kind] : isHovered ? "var(--selected)" : undefined }}
                    title={ann ? `${ann.name}, offset 0x${(windowOffset + ann.offset).toString(16)}` : undefined}
                  >
                    {toHexByte(b)}
                  </span>
                );
              })}
            </span>
            <span className="text-text-3">
              {row.bytes.map((b, i) => {
                const relOffset = row.offset - windowOffset + i;
                const ann = annotationAtOffset(annotations, relOffset);
                const isHovered = ann != null && ann.name === hoveredName;
                return (
                  <span key={i} className={isHovered ? "bg-[var(--selected)] text-text" : undefined}>
                    {byteToAscii(b)}
                  </span>
                );
              })}
            </span>
          </div>
        );
      })}
      <div style={{ height: paddingBottom }} aria-hidden />
    </div>
  );
}
