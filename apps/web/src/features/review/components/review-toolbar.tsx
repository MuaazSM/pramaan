import { useState } from "react";
import { LayoutGrid, Grid3x3, Square, Play, Pause, Rewind, FastForward, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { usePlayheadStore, type GridLayout } from "../store/playhead";
import type { FrameRefIndex } from "../lib/frame-index";

const LAYOUTS: { value: GridLayout; icon: typeof Square; label: string }[] = [
  { value: 1, icon: Square, label: "Single" },
  { value: 4, icon: LayoutGrid, label: "Quad" },
  { value: 9, icon: Grid3x3, label: "Nine-up" },
];

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-line-strong bg-control px-1 py-0.5 font-mono text-[10px] leading-none text-text-2">
      {children}
    </kbd>
  );
}

export function ReviewToolbar({
  goToInputRef,
  frameIndex,
  channelNumbers,
}: {
  goToInputRef: React.RefObject<HTMLInputElement | null>;
  frameIndex: FrameRefIndex;
  channelNumbers: number[];
}) {
  const gridLayout = usePlayheadStore((s) => s.gridLayout);
  const setGridLayout = usePlayheadStore((s) => s.setGridLayout);
  const activeChannels = usePlayheadStore((s) => s.activeChannels);
  const setActiveChannels = usePlayheadStore((s) => s.setActiveChannels);
  const playing = usePlayheadStore((s) => s.playing);
  const rate = usePlayheadStore((s) => s.rate);
  const cycleShuttle = usePlayheadStore((s) => s.cycleShuttle);
  const jumpTo = usePlayheadStore((s) => s.jumpTo);
  const rangeSelection = usePlayheadStore((s) => s.rangeSelection);
  const setRangeSelection = usePlayheadStore((s) => s.setRangeSelection);

  const [goToValue, setGoToValue] = useState("");
  const [goToError, setGoToError] = useState(false);

  function submitGoTo() {
    const ok = jumpTo(goToValue, (id) => frameIndex.byId.get(id) ?? null);
    setGoToError(!ok);
    if (ok) setGoToValue("");
  }

  function toggleChannel(ch: number) {
    setActiveChannels(
      activeChannels.includes(ch) ? activeChannels.filter((c) => c !== ch) : [...activeChannels, ch].sort((a, b) => a - b),
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line bg-panel px-3 py-2">
      <div className="flex items-center gap-1 rounded-[var(--radius-control)] border border-line-strong bg-control p-0.5">
        {LAYOUTS.map(({ value, icon: Icon, label }) => (
          <Tooltip key={value}>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => setGridLayout(value)}
                aria-pressed={gridLayout === value}
                aria-label={`${label} grid`}
                className={cn(
                  "focus-ring flex size-7 items-center justify-center rounded-[calc(var(--radius-control)-2px)] text-text-2 hover:text-text",
                  gridLayout === value && "bg-accent text-white",
                )}
              >
                <Icon size={14} strokeWidth={1.5} />
              </button>
            </TooltipTrigger>
            <TooltipContent>{label} grid</TooltipContent>
          </Tooltip>
        ))}
      </div>

      <div className="h-5 w-px bg-line" aria-hidden />

      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Shuttle reverse"
              onClick={() => cycleShuttle(-1)}
              className={cn(rate < 0 && playing && "text-accent-text")}
            >
              <Rewind size={14} strokeWidth={1.5} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Reverse <Kbd>J</Kbd>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={playing ? "Pause" : "Play"} onClick={() => cycleShuttle(playing ? 0 : 1)}>
              {playing ? <Pause size={14} strokeWidth={1.5} /> : <Play size={14} strokeWidth={1.5} />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Play / pause <Kbd>K</Kbd> / <Kbd>Space</Kbd>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Shuttle forward"
              onClick={() => cycleShuttle(1)}
              className={cn(rate > 0 && playing && "text-accent-text")}
            >
              <FastForward size={14} strokeWidth={1.5} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Forward <Kbd>L</Kbd>
          </TooltipContent>
        </Tooltip>
        {playing && rate !== 0 && (
          <span className="font-mono text-[11px] tabular-nums text-text-2">{Math.abs(rate)}x</span>
        )}
      </div>

      <div className="h-5 w-px bg-line" aria-hidden />

      <div className="flex items-center gap-1.5">
        {channelNumbers.map((ch) => (
          <button
            key={ch}
            type="button"
            onClick={() => toggleChannel(ch)}
            aria-pressed={activeChannels.includes(ch)}
            className={cn(
              "focus-ring rounded-full border px-2 py-0.5 text-[11px] font-medium",
              activeChannels.includes(ch)
                ? "border-line-strong bg-control text-text"
                : "border-line bg-transparent text-text-3 hover:text-text-2",
            )}
          >
            CH{ch}
          </button>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        {rangeSelection && (
          <button
            type="button"
            onClick={() => setRangeSelection(null)}
            className="focus-ring flex items-center gap-1 rounded-full border border-[color-mix(in_oklab,var(--brand-500)_40%,transparent)] bg-[var(--selected)] px-2 py-0.5 text-[11px] font-medium text-accent-text"
          >
            Range selected
            <X size={11} strokeWidth={1.75} />
          </button>
        )}
        <div className="flex items-center gap-1.5">
          <Input
            ref={goToInputRef}
            value={goToValue}
            onChange={(e) => {
              setGoToValue(e.target.value);
              setGoToError(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitGoTo();
            }}
            placeholder="14:02:37"
            aria-label="Go to timecode"
            aria-invalid={goToError}
            className={cn("h-7 w-32 font-mono text-xs", goToError && "border-danger")}
          />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="secondary" size="sm" onClick={submitGoTo} className="h-7">
                Go
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Jump to timecode <Kbd>G</Kbd>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
