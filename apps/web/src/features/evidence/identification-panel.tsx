import { useQuery } from "@tanstack/react-query";
import { ScanSearch, Hash } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { TierBadge, type Tier } from "@/components/signature/tier-badge";
import { api } from "@/api/client";

/**
 * Identification: ranked vendor matches with reasons + OEM lineage ("Sold as: …"), per
 * docs/04-FRONTEND.md §5's evidence-detail brief. Synthetic-corpus honesty (CLAUDE.md §7): every
 * label here comes straight from the fingerprint fixture/route, never rewritten with a
 * "compatible" claim in this component.
 */
export function IdentificationPanel({ eid }: { eid: string }) {
  const query = useQuery({
    queryKey: ["fingerprint", eid],
    queryFn: async () => (await api.GET("/api/evidence/{eid}/fingerprint", { params: { path: { eid } } })).data ?? [],
  });

  const matches = [...(query.data ?? [])].sort((a, b) => b.confidence - a.confidence);

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-panel p-4">
      <div className="mb-3 flex items-center gap-2">
        <ScanSearch size={14} strokeWidth={1.75} className="text-text-3" />
        <h2 className="text-[13px] font-medium text-text">Identification</h2>
      </div>

      {query.isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-20 w-full" />
        </div>
      ) : matches.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-text-2">No fingerprint run yet — run a scan to identify this image.</p>
      ) : (
        <ol className="flex flex-col gap-3">
          {matches.map((match, i) => (
            <li key={`${match.family}-${i}`} className="rounded-[var(--radius-control)] border border-line bg-card p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-text">{match.display_name}</span>
                  <TierBadge tier={match.tier as Tier} />
                </div>
                <span className="font-mono text-xs tabular-nums text-text-2">{Math.round(match.confidence * 100)}% confidence</span>
              </div>

              <div className="mb-2 h-1 w-full overflow-hidden rounded-full bg-control">
                <div className="h-full rounded-full bg-accent" style={{ width: `${match.confidence * 100}%` }} />
              </div>

              <dl className="mb-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                <Field label="Platform" value={match.platform} />
                <Field label="Serial" value={match.serial} mono />
                <Field label="FS version" value={match.fs_version} mono />
              </dl>

              {match.model && (
                <p className="mb-2 rounded-[var(--radius-control)] bg-control px-2 py-1.5 text-xs text-text-2">
                  <span className="text-text-3">OEM lineage · </span>
                  {match.model}
                </p>
              )}

              <ul className="flex flex-col gap-1">
                {match.evidence.map((reason, ri) => (
                  <li key={ri} className="flex items-start gap-1.5 text-xs text-text-2">
                    <Hash size={11} strokeWidth={1.75} className="mt-0.5 shrink-0 text-text-3" />
                    <span className="font-mono">{reason}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Field({ label, value, mono }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-text-3">{label}</dt>
      <dd className={mono ? "font-mono text-text" : "text-text"}>{value ?? "—"}</dd>
    </div>
  );
}
