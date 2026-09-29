import { ShieldCheck, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortHash, formatTimecode } from "@/lib/format";

/**
 * Signature component 3 (BRAND.md §8): footer strip on every case screen —
 * chain head hash, entry count, last anchor time.
 */
export function CustodySeal({
  ok,
  entryCount,
  headHash,
  anchoredAtIso,
  className,
}: {
  ok: boolean;
  entryCount: number;
  headHash: string;
  anchoredAtIso: string;
  className?: string;
}) {
  const Icon = ok ? ShieldCheck : ShieldAlert;
  return (
    <div
      className={cn(
        "flex h-7 items-center gap-2 border-t border-line bg-panel px-4 text-xs text-text-2",
        className,
      )}
    >
      <Icon size={13} strokeWidth={1.75} className={ok ? "text-ok" : "text-danger"} />
      <span className={cn("font-medium", ok ? "text-ok" : "text-danger")}>Chain {ok ? "✓" : "✗"}</span>
      <span>{entryCount} entries</span>
      <span className="text-text-3">·</span>
      <span>
        head <span className="font-mono text-text-2">{shortHash(headHash)}</span>
      </span>
      <span className="text-text-3">·</span>
      <span className="font-mono">{formatTimecode(anchoredAtIso)}</span>
    </div>
  );
}
