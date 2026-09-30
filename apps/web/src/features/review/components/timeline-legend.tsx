/**
 * F7: a legend for the timeline canvas's track colours/layers (docs/progress/F7.md). The canvas
 * itself (timeline/draw.ts) draws three sub-rows per channel — coverage (solid/hatched/dotted),
 * deleted-then-recovered, and a motion-activity strip — plus coloured log-event markers on the
 * ruler. None of that encoding was explained anywhere in the UI; this strip is the explanation,
 * kept as plain DOM (not canvas) so it stays crisp text and needs no redraw.
 */
export function TimelineLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-panel px-3 py-1.5 text-caption text-text-3">
      <LegendSwatch className="bg-[var(--ch-1)]" label="Recorded" />
      <LegendSwatch className="bg-[var(--ch-1)] opacity-40 [background-image:repeating-linear-gradient(45deg,transparent,transparent_2px,rgba(255,255,255,0.5)_2px,rgba(255,255,255,0.5)_3px)]" label="Recovered from deleted space" />
      <LegendSwatch className="border border-dashed border-[var(--ch-1)] bg-transparent" label="Layout inferred" />
      <LegendSwatch className="bg-recovered" label="Deletion window" />
      <LegendSwatch className="bg-ok" label="Motion detected" />
      <span className="ml-auto flex items-center gap-1">
        <span className="h-2.5 w-px bg-[var(--brand-400)]" aria-hidden />
        Playhead
      </span>
    </div>
  );
}

function LegendSwatch({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2.5 w-4 shrink-0 rounded-[2px] ${className}`} aria-hidden />
      {label}
    </span>
  );
}
