import { useState } from "react";
import { Check, Clock, TriangleAlert, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortHash } from "@/lib/format";

export type IntegrityState = "verified" | "pending" | "mismatch";

const CONFIG: Record<IntegrityState, { label: string; icon: typeof Check; colorClass: string; dotClass: string }> = {
  verified: { label: "verified", icon: Check, colorClass: "text-ok", dotClass: "bg-ok" },
  pending: { label: "pending", icon: Clock, colorClass: "text-warn", dotClass: "bg-warn" },
  mismatch: { label: "mismatch", icon: TriangleAlert, colorClass: "text-danger", dotClass: "bg-danger" },
};

/**
 * Signature component 1 (BRAND.md §8): `[● verified] sha256 a41f09c2…9e1d` + copy.
 * On transition to "verified" the dot draws a one-cycle checkmark stroke (BRAND.md §6 "signature moment").
 */
export function IntegrityChip({
  state,
  hash,
  algo = "sha256",
  className,
}: {
  state: IntegrityState;
  hash: string;
  algo?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const { label, icon: Icon, colorClass, dotClass } = CONFIG[state];

  async function copy() {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // clipboard unavailable (e.g. headless screenshot run) — no-op
    }
  }

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-control px-2 py-1 text-xs",
        className,
      )}
      title={hash}
    >
      <span className={cn("relative flex size-3.5 items-center justify-center rounded-full", dotClass, "bg-opacity-100")}>
        <Icon size={9} strokeWidth={2.5} className="text-[var(--ink-950)]" />
      </span>
      <span className={cn("font-medium", colorClass)}>{label}</span>
      <span className="text-text-3">·</span>
      <span className="font-mono text-text-2">
        {algo} {shortHash(hash)}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy full hash"
        className="focus-ring ml-0.5 rounded p-0.5 text-text-3 hover:bg-[var(--ink-600)] hover:text-text"
      >
        {copied ? <Check size={11} strokeWidth={1.75} className="text-ok" /> : <Copy size={11} strokeWidth={1.75} />}
      </button>
    </div>
  );
}
