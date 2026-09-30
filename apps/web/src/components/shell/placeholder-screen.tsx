import type { LucideIcon } from "lucide-react";
import { ScreenShell } from "@/components/shell/screen-shell";
import type { LineageSegment } from "@/components/signature/lineage-breadcrumb";

/**
 * Designed placeholder for routes not built in this wave (docs/04-FRONTEND.md §5: "all other
 * routes as designed placeholders"). Not a blank page — states what the screen will do and who
 * owns it, in brand voice.
 */
export function PlaceholderScreen({
  segments,
  caseId,
  icon: Icon,
  title,
  description,
  owner,
}: {
  segments: LineageSegment[];
  caseId?: string;
  icon: LucideIcon;
  title: string;
  description: string;
  owner: string;
}) {
  return (
    <ScreenShell segments={segments} caseId={caseId} showCustodySeal={Boolean(caseId)}>
      <div className="flex h-full flex-col items-center justify-center gap-4 p-10 text-center">
        <div className="flex size-12 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
          <Icon size={22} strokeWidth={1.5} className="text-text-3" />
        </div>
        <div className="max-w-md">
          <h1 className="text-page-title text-text">{title}</h1>
          <p className="mt-1.5 text-base text-text-2">{description}</p>
        </div>
        <span className="rounded-full border border-line-strong bg-control px-2.5 py-1 text-caption text-text-3">
          Designed placeholder, built by {owner}
        </span>
      </div>
    </ScreenShell>
  );
}
