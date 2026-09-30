import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * F7 "bytes on demand" primitive: a collapsed-by-default disclosure for raw IDs, byte offsets,
 * full hashes and other examiner-grade detail that a first-time viewer doesn't need to understand
 * the story, but an examiner must still be able to reach. Built on native `<details>`/`<summary>`
 * so it's keyboard-operable and screen-reader-correct for free, with no JS state and no motion
 * beyond the browser's own (which respects `prefers-reduced-motion` since there is none added
 * here). Every screen that hides raw IDs/offsets/hashes behind a summary uses this, not a bespoke
 * expander, so the pattern reads the same everywhere.
 */
export function TechnicalDetails({
  summary,
  children,
  className,
  defaultOpen,
}: {
  summary: string;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) {
  return (
    <details
      className={cn("group rounded-[var(--radius-control)] border border-line bg-card", className)}
      open={defaultOpen}
    >
      <summary className="focus-ring flex cursor-pointer list-none items-center gap-1.5 rounded-[var(--radius-control)] px-3 py-2 text-label text-text-2 select-none [&::-webkit-details-marker]:hidden">
        <ChevronRight size={12} strokeWidth={1.75} className="shrink-0 text-text-3 transition-transform group-open:rotate-90" />
        {summary}
      </summary>
      <div className="border-t border-line px-3 py-2.5">{children}</div>
    </details>
  );
}
