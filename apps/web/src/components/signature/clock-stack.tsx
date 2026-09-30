import { cn } from "@/lib/utils";
import { formatTimecode } from "@/lib/format";

export interface ClockReading {
  key: "header" | "index" | "osd" | "normalised";
  label: string;
  iso: string | null;
  confidence: number | null;
  offsetLabel?: string;
}

/**
 * Signature component 5 (BRAND.md §8): four clocks stacked for a frame — frame header, index,
 * on-screen OCR, normalised IST — with the chosen value highlighted and confidence shown.
 */
export function ClockStack({
  readings,
  chosenKey,
  className,
}: {
  readings: ClockReading[];
  chosenKey: ClockReading["key"];
  className?: string;
}) {
  return (
    <dl className={cn("flex flex-col gap-1", className)}>
      {readings.map((r) => {
        const chosen = r.key === chosenKey;
        return (
          <div
            key={r.key}
            className={cn(
              "flex items-center justify-between gap-3 rounded-[var(--radius-control)] px-2 py-1.5",
              chosen ? "border border-[color-mix(in_oklab,var(--brand-500)_45%,transparent)] bg-[var(--selected)]" : "border border-transparent",
            )}
          >
            <dt className="flex items-center gap-1.5 text-label text-text-2">
              {chosen && <span className="size-1.5 rounded-full bg-accent" aria-hidden />}
              {r.label}
            </dt>
            <dd className="flex items-center gap-2 tabular-nums">
              <span className={cn("font-data text-sm", chosen ? "text-text" : "text-text-2")}>
                {r.iso ? formatTimecode(r.iso) : "—"}
              </span>
              {r.offsetLabel && <span className="text-caption text-warn">{r.offsetLabel}</span>}
              {r.confidence != null && (
                <span className="text-caption text-text-2">{Math.round(r.confidence * 100)}%</span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
