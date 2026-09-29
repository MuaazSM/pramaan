import { cn } from "@/lib/utils";

/** Skeleton loader matching final layout dimensions — no layout shift. Static under reduced-motion. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton-shimmer rounded-[var(--radius-control)]", className)} />;
}
