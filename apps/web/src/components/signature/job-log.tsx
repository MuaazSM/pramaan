import { useState } from "react";
import { Check, ChevronDown, CircleDashed, LoaderCircle, X, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";
import type { components } from "@/api/schema.gen";

type JobStage = components["schemas"]["JobStage"];

const STAGE_ICON: Record<JobStage["status"], typeof Check> = {
  done: Check,
  running: LoaderCircle,
  pending: CircleDashed,
  failed: X,
  skipped: SkipForward,
};
const STAGE_CLASS: Record<JobStage["status"], string> = {
  done: "text-ok",
  running: "text-warn animate-spin",
  pending: "text-text-3",
  failed: "text-danger",
  skipped: "text-text-3",
};

/**
 * Vercel-style deployment log: stage list with ticks + a collapsible raw log.
 * Used by the job drawer and evidence/case scan panels.
 */
export function JobLog({
  stages,
  logLines,
  pct,
  className,
}: {
  stages: JobStage[];
  logLines: string[];
  pct: number;
  className?: string;
}) {
  const [logOpen, setLogOpen] = useState(false);
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-control">
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-[var(--dur-slow)] ease-[var(--ease)]"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-9 shrink-0 text-right font-mono text-xs tabular-nums text-text-2">{Math.round(pct)}%</span>
      </div>

      <ol className="flex flex-col gap-0.5">
        {stages.map((stage) => {
          const Icon = STAGE_ICON[stage.status];
          return (
            <li key={stage.name} className="flex items-center gap-2 rounded-[var(--radius-control)] px-2 py-1.5">
              <Icon size={13} strokeWidth={2} className={cn("shrink-0", STAGE_CLASS[stage.status])} />
              <span className={cn("text-xs", stage.status === "pending" ? "text-text-2" : "text-text")}>
                {stage.name.replace(/_/g, " ")}
              </span>
              {stage.message && <span className="truncate text-[11px] text-text-2">{stage.message}</span>}
              {stage.status === "running" && (
                <span className="ml-auto font-mono text-[11px] tabular-nums text-warn">{Math.round(stage.pct)}%</span>
              )}
            </li>
          );
        })}
      </ol>

      <div>
        <button
          type="button"
          onClick={() => setLogOpen((v) => !v)}
          className="focus-ring flex items-center gap-1 rounded px-1 text-[11px] font-medium text-text-2 hover:text-text"
        >
          <ChevronDown size={12} strokeWidth={1.75} className={cn("transition-transform", logOpen && "rotate-180")} />
          {logOpen ? "Hide" : "Show"} log ({logLines.length})
        </button>
        {logOpen && (
          <pre className="mt-2 max-h-48 overflow-y-auto rounded-[var(--radius-control)] border border-line bg-[var(--ink-950)] p-2 font-mono text-[11px] leading-relaxed text-text-2">
            {logLines.join("\n")}
          </pre>
        )}
      </div>
    </div>
  );
}
