import { Search, Sun, Moon, LoaderCircle, Rows3, Rows2, Keyboard } from "lucide-react";
import { LineageBreadcrumb, type LineageSegment } from "@/components/signature/lineage-breadcrumb";
import { useUiStore } from "@/store/ui";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { components } from "@/api/schema.gen";

type Job = components["schemas"]["Job"];

export function TopBar({ segments, runningJob }: { segments: LineageSegment[]; runningJob?: Job }) {
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const density = useUiStore((s) => s.density);
  const setDensity = useUiStore((s) => s.setDensity);
  const setCommandPaletteOpen = useUiStore((s) => s.setCommandPaletteOpen);
  const setJobDrawerOpen = useUiStore((s) => s.setJobDrawerOpen);
  const setShortcutSheetOpen = useUiStore((s) => s.setShortcutSheetOpen);

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-canvas px-4">
      <LineageBreadcrumb segments={segments} className="min-w-0 flex-1" />

      <button
        type="button"
        onClick={() => setCommandPaletteOpen(true)}
        className="focus-ring flex h-7 items-center gap-2 rounded-[var(--radius-control)] border border-line-strong bg-control px-2.5 text-xs text-text-2 hover:text-text"
      >
        <Search size={13} strokeWidth={1.75} className="text-text-3" />
        Search
        <kbd className="ml-2 rounded border border-line-strong bg-panel px-1 font-mono text-[10px] text-text-2">
          {"⌘"}K
        </kbd>
      </button>

      {runningJob && (
        <button
          type="button"
          onClick={() => setJobDrawerOpen(true)}
          className="focus-ring flex h-7 items-center gap-2 rounded-[var(--radius-control)] border border-line-strong bg-control px-2.5 text-xs text-warn hover:brightness-110"
        >
          <LoaderCircle size={13} strokeWidth={2} className="animate-spin" />
          {runningJob.kind} {"·"} {Math.round(runningJob.pct)}%
        </button>
      )}

      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => setDensity(density === "comfortable" ? "compact" : "comfortable")}
            aria-label="Toggle density"
            className="focus-ring flex size-7 items-center justify-center rounded-[var(--radius-control)] text-text-3 hover:bg-control hover:text-text"
          >
            {density === "comfortable" ? <Rows3 size={15} strokeWidth={1.5} /> : <Rows2 size={15} strokeWidth={1.5} />}
          </button>
        </TooltipTrigger>
        <TooltipContent>{density === "comfortable" ? "Switch to compact" : "Switch to comfortable"}</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => setShortcutSheetOpen(true)}
            aria-label="Keyboard shortcuts"
            className="focus-ring flex size-7 items-center justify-center rounded-[var(--radius-control)] text-text-3 hover:bg-control hover:text-text"
          >
            <Keyboard size={15} strokeWidth={1.5} />
          </button>
        </TooltipTrigger>
        <TooltipContent>
          Keyboard shortcuts <kbd className="ml-1 rounded border border-line-strong bg-panel px-1 font-mono text-[10px]">?</kbd>
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className={cn(
              "focus-ring flex size-7 items-center justify-center rounded-[var(--radius-control)] text-text-3 hover:bg-control hover:text-text",
            )}
          >
            {theme === "dark" ? <Sun size={15} strokeWidth={1.5} /> : <Moon size={15} strokeWidth={1.5} />}
          </button>
        </TooltipTrigger>
        <TooltipContent>{theme === "dark" ? "Switch to light" : "Switch to dark"}</TooltipContent>
      </Tooltip>
    </header>
  );
}
