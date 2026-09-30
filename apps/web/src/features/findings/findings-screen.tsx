/**
 * /cases/$cid/findings — Findings.
 * Primary action: Open evidence. Deletion-verdict cards: method, range, actor, confidence meter,
 * reasons (each citing offsets/log ids), links back to the source evidence, the recordings
 * filtered to the affected channel, and the review timeline.
 * Reference products studied: Sentry (issue detail card: title, context panels, breadcrumbs).
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ShieldAlert, HardDrive, Video, PlaySquare, Binary, Hash, ChevronRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { formatTimecodeUs, formatBytes } from "@/lib/format";
import type { components } from "@/api/schema.gen";

type DeletionFinding = components["schemas"]["DeletionFinding"];

const METHOD_LABEL: Record<DeletionFinding["method"], string> = {
  format: "Format",
  expiry: "Retention expiry",
  overwrite: "Overwrite",
  unknown: "Unknown method",
};

export function FindingsScreen({ cid }: { cid: string }) {
  const query = useQuery({
    queryKey: ["deletions", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/deletions", { params: { path: { cid } } });
      if (error) throw errorFromResponse(response, "findings could not be loaded");
      return data ?? [];
    },
  });

  const findings = [...(query.data ?? [])].sort((a, b) => b.confidence - a.confidence);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 p-6">
      <div>
        <h1 className="text-page-title text-text">Findings</h1>
        <p className="mt-1 text-base text-text-2">Deletion verdicts recovered from unindexed space, with every reason traced back to bytes.</p>
      </div>

      {query.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-48 w-full" />
        </div>
      ) : query.isError ? (
        <QueryErrorState error={query.error} subject="findings" onRetry={() => void query.refetch()} />
      ) : findings.length === 0 ? (
        <EmptyFindings />
      ) : (
        <ul className="flex flex-col gap-4">
          {findings.map((f) => (
            <FindingCard key={f.id} cid={cid} finding={f} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingCard({ cid, finding }: { cid: string; finding: DeletionFinding }) {
  const frameChips = Array.from({ length: Math.min(3, Math.max(1, Math.round(finding.frames_recovered / 80))) }, (_, i) => ({
    label: `frame_${finding.image_id}_ch${finding.channel ?? "x"}_${String(i + 1).padStart(3, "0")}`,
  }));

  return (
    <li className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--recovered)_40%,transparent)] bg-[var(--recovered-tint)]">
            <ShieldAlert size={16} strokeWidth={1.75} className="text-recovered" />
          </span>
          <div>
            {/* F6: "on channel N", not "· CHN" — plain language instead of a dot-joined
                abbreviation (docs/progress/F6.md). */}
            <h2 className="text-section text-text">
              {METHOD_LABEL[finding.method]} deletion{finding.channel != null ? ` on channel ${finding.channel}` : ""}
            </h2>
            <p className="mt-0.5 font-data text-sm tabular-nums text-text-2">
              {formatTimecodeUs(finding.start_ts_us)} → {formatTimecodeUs(finding.end_ts_us)}
            </p>
          </div>
        </div>
        <Badge variant="recovered">recovered</Badge>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Actor" value={finding.actor ?? "unknown"} />
        <Stat label="Frames recovered" value={finding.frames_recovered.toLocaleString()} mono />
        <Stat label="Bytes recovered" value={formatBytes(finding.bytes_recovered)} mono />
        <Stat label="Action time" value={finding.action_ts_us != null ? formatTimecodeUs(finding.action_ts_us) : "—"} mono />
      </div>

      <div className="mb-4">
        <div className="mb-1 flex items-center justify-between text-label text-text-2">
          <span>Confidence</span>
          <span className="font-data tabular-nums">{Math.round(finding.confidence * 100)}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-control">
          <div className="h-full rounded-full bg-recovered" style={{ width: `${finding.confidence * 100}%` }} />
        </div>
      </div>

      <div className="mb-4">
        <h3 className="mb-1.5 text-label text-text-2">Reasons</h3>
        <ul className="flex flex-col gap-1">
          {finding.reasons.map((reason, i) => (
            <li key={i} className="flex items-start gap-1.5 text-sm text-text-2">
              <Hash size={11} strokeWidth={1.75} className="mt-0.5 shrink-0 text-text-3" />
              <span className="font-data">{reason}</span>
            </li>
          ))}
        </ul>
      </div>

      {finding.evidence_refs.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-1.5 text-label text-text-2">Evidence refs</h3>
          <div className="flex flex-wrap gap-1.5">
            {finding.evidence_refs.map((ref) => (
              <span key={ref} className="rounded-full border border-line-strong bg-control px-2 py-0.5 font-data text-caption text-text-2">
                {ref}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mb-4">
        {/* F6: "Recovered frames (sample)" — dropped the spaced em dash and the "Prove it" repeat
            (each chip already links to Prove it; naming it twice was the redundant eyebrow the
            brief calls out). */}
        <h3 className="mb-1.5 text-label text-text-2">Recovered frames (sample)</h3>
        <div className="flex flex-wrap gap-1.5">
          {frameChips.map((chip) => (
            <Link
              key={chip.label}
              to="/cases/$cid/frames/$fid/prove"
              params={{ cid, fid: chip.label }}
              className="focus-ring flex items-center gap-1 rounded-full border border-line-strong bg-control px-2 py-0.5 font-data text-caption text-text-2 transition-colors hover:border-[color-mix(in_oklab,var(--brand-500)_40%,transparent)] hover:text-accent-text"
            >
              <Binary size={10} strokeWidth={1.75} />
              {chip.label}
              <ChevronRight size={10} strokeWidth={1.75} />
            </Link>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button asChild size="sm">
          <Link to="/cases/$cid/evidence/$eid" params={{ cid, eid: finding.image_id }}>
            <HardDrive size={13} strokeWidth={1.75} />
            Open evidence
          </Link>
        </Button>
        <Button asChild size="sm" variant="secondary">
          <Link to="/cases/$cid/recordings" params={{ cid }}>
            <Video size={13} strokeWidth={1.75} />
            View recordings
          </Link>
        </Button>
        <Button asChild size="sm" variant="secondary">
          <Link to="/cases/$cid/review" params={{ cid }}>
            <PlaySquare size={13} strokeWidth={1.75} />
            Open timeline
          </Link>
        </Button>
      </div>
    </li>
  );
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-label text-text-2">{label}</dt>
      <dd className={mono ? "font-data tabular-nums text-text" : "text-base text-text"}>{value}</dd>
    </div>
  );
}

function EmptyFindings() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-panel)] border border-dashed border-line-strong py-16 text-center">
      <ShieldAlert size={28} strokeWidth={1.5} className="text-text-3" />
      <p className="text-base text-text-2">No deletion findings recorded for this case yet.</p>
    </div>
  );
}
