import { ChevronRight } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";

export interface LineageSegment {
  label: string;
  to?: string;
}

/**
 * Signature component 2 (BRAND.md §8): Disk → Image → Scan run → Recording → Frame.
 * Every segment but the last is a link; the current object is plain text.
 */
export function LineageBreadcrumb({ segments, className }: { segments: LineageSegment[]; className?: string }) {
  return (
    <nav aria-label="Lineage" className={cn("flex min-w-0 items-center gap-1 text-xs text-text-2", className)}>
      {segments.map((seg, i) => {
        const isLast = i === segments.length - 1;
        return (
          <span key={`${seg.label}-${i}`} className="flex min-w-0 items-center gap-1">
            {i > 0 && <ChevronRight size={12} strokeWidth={1.5} className="shrink-0 text-text-3" />}
            {seg.to && !isLast ? (
              <Link
                to={seg.to}
                className="focus-ring truncate rounded px-0.5 hover:text-accent-text hover:underline"
              >
                {seg.label}
              </Link>
            ) : (
              <span className={cn("truncate px-0.5", isLast && "font-medium text-text")}>{seg.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
