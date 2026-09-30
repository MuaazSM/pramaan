import { Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * F7: a small "explain this term in place" affordance — an (i) icon that shows a plain-language
 * tooltip on hover/focus. Used next to jargon (tier, clock confidence, carved, custody chain,
 * normalised, …) instead of leaving the word unexplained. Keyboard-reachable (Radix Tooltip opens
 * on focus, not just hover) and never the only way to reach the information it explains — it
 * supplements a label, it never replaces one.
 */
export function InfoHint({ label, className }: { label: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={`focus-ring inline-flex size-3.5 shrink-0 items-center justify-center rounded-full text-text-3 hover:text-text-2 ${className ?? ""}`}
          aria-label={label}
        >
          <Info size={12} strokeWidth={1.75} />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64 text-pretty">{label}</TooltipContent>
    </Tooltip>
  );
}
