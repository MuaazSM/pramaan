import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface AiSentence {
  text: string;
  evidenceIds: string[];
}

/**
 * Signature component 6 (BRAND.md §8): violet dashed border, "AI draft · needs examiner review"
 * label, every sentence carries evidence-id chips, explicit "Accept into report" action.
 * The LLM never produces a finding (CLAUDE.md rule 6) — this is always a labelled draft.
 */
export function AIDraftBlock({
  sentences,
  onAccept,
  onReject,
  className,
}: {
  sentences: AiSentence[];
  onAccept?: () => void;
  onReject?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-card)] border border-dashed border-[color-mix(in_oklab,var(--ai)_55%,transparent)] bg-[var(--ai-tint)] p-3",
        className,
      )}
    >
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ai">
        <Sparkles size={13} strokeWidth={1.75} />
        AI draft {"·"} needs examiner review
      </div>
      <div className="flex flex-col gap-2 text-[13px] leading-relaxed text-text">
        {sentences.map((s, i) => (
          <p key={i}>
            {s.text}{" "}
            {s.evidenceIds.map((id) => (
              <span
                key={id}
                className="ml-1 inline-flex items-center rounded-full border border-line-strong bg-control px-1.5 py-0.5 font-mono text-[10px] text-text-2"
              >
                {id}
              </span>
            ))}
          </p>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="sm" variant="secondary" onClick={onAccept}>
          Accept into report
        </Button>
        <Button size="sm" variant="ghost" onClick={onReject}>
          Reject
        </Button>
      </div>
    </div>
  );
}
