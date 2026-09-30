import { cn } from "@/lib/utils";

export type Tier = "A" | "B" | "C";

const TIER_LABEL: Record<Tier, string> = { A: "parsed", B: "inferred", C: "carved" };
const TIER_CLASS: Record<Tier, string> = {
  A: "text-ok border-[color-mix(in_oklab,var(--ok)_40%,transparent)] bg-[var(--ok-tint)]",
  B: "text-inferred border-[color-mix(in_oklab,var(--inferred)_40%,transparent)] bg-[color-mix(in_oklab,var(--inferred)_14%,transparent)]",
  C: "text-recovered border-[color-mix(in_oklab,var(--recovered)_40%,transparent)] bg-[var(--recovered-tint)]",
};

/** Signature component 4 (BRAND.md §8): `A · parsed`, `B · inferred`, `C · carved`. */
export function TierBadge({ tier, className }: { tier: Tier; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-caption",
        TIER_CLASS[tier],
        className,
      )}
    >
      {/* BRAND.md §8 writes this exact format ("A · parsed") — the one signature component the
          dot stays in besides CustodySeal (docs/progress/F6.md). */}
      <span className="font-data">{tier}</span>
      <span className="opacity-70">{"·"}</span>
      {TIER_LABEL[tier]}
    </span>
  );
}
