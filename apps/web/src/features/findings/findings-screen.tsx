/**
 * /cases/$cid/findings — Findings.
 * Primary action: Open evidence. Deletion-verdict cards: method, range, actor, confidence meter,
 * reasons (each citing offsets/log ids), links back to the source evidence, the recordings
 * filtered to the affected channel, and the review timeline.
 * Reference products studied: Sentry (issue detail card: title, context panels, breadcrumbs).
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ShieldAlert, HardDrive, Video, PlaySquare, Binary, ChevronRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InfoHint } from "@/components/ui/info-hint";
import { TechnicalDetails } from "@/components/ui/technical-details";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { formatTimecodeUs, formatDuration } from "@/lib/format";
import { capList, confidenceExplanation, findingHeadline, humanizeReason, recoveredSummary } from "@/lib/humanize";
import type { components } from "@/api/schema.gen";

type DeletionFinding = components["schemas"]["DeletionFinding"];

const METHOD_LABEL: Record<DeletionFinding["method"], string> = {
  format: "Format",
  expiry: "Retention expiry",
  overwrite: "Overwrite",
  unknown: "Unknown method",
};

/** How many sample frame ids to show inline before collapsing the rest. */
const SAMPLE_FRAME_COUNT = 4;

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
  // The real API's evidence_refs are the actual recovered frame ids (frm_…, sometimes joined by a
  // handful of log/recording ids) — often 100+ for a large deletion. Show a headline count plus a
  // few real, clickable samples instead of dumping every id as a chip; the rest stay one click
  // away in "Technical details" rather than gone.
  const { shown: sampleRefs, more: moreRefs } = capList(finding.evidence_refs, SAMPLE_FRAME_COUNT);
  const windowSeconds = Math.max(0, (finding.end_ts_us - finding.start_ts_us) / 1_000_000);

  return (
    <li className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--recovered)_40%,transparent)] bg-[var(--recovered-tint)]">
            <ShieldAlert size={16} strokeWidth={1.75} className="text-recovered" />
          </span>
          <div>
            {/* F7: the headline sentence leads — plain language built from the same structured
                fields the stat grid below shows as numbers (docs/progress/F7.md). */}
            <p className="text-base text-text">{findingHeadline(finding)}</p>
            <p className="mt-1 flex items-center gap-1 text-label text-text-3">
              {METHOD_LABEL[finding.method]} deletion{finding.channel != null ? ` on channel ${finding.channel}` : ""}
              {" · "}
              <DeletionWindowBar startUs={finding.start_ts_us} endUs={finding.end_ts_us} />
            </p>
          </div>
        </div>
        <Badge variant="recovered">recovered</Badge>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Actor" value={finding.actor ?? "unknown"} />
        <Stat label="Recovered" value={recoveredSummary(finding.frames_recovered, finding.bytes_recovered)} />
        <Stat label="Deletion window" value={`${formatDuration(windowSeconds)} long`} />
        <Stat label="Action time" value={finding.action_ts_us != null ? formatTimecodeUs(finding.action_ts_us) : "—"} mono />
      </div>

      <div className="mb-4">
        <div className="mb-1 flex items-center gap-1.5 text-label text-text-2">
          <span>Confidence</span>
          <span className="ml-auto font-data tabular-nums">{Math.round(finding.confidence * 100)}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-control">
          <div className="h-full rounded-full bg-recovered" style={{ width: `${finding.confidence * 100}%` }} />
        </div>
        <p className="mt-1 text-caption text-text-3">{confidenceExplanation(finding.reasons.length)}</p>
      </div>

      <div className="mb-4">
        <h3 className="mb-1.5 text-label text-text-2">Reasons</h3>
        <ul className="flex flex-col gap-1">
          {finding.reasons.map((reason, i) => (
            <li key={i} className="flex items-start gap-1.5 text-sm text-text-2">
              <span className="mt-1.5 size-1 shrink-0 rounded-full bg-text-3" aria-hidden />
              <span>{humanizeReason(reason)}</span>
            </li>
          ))}
        </ul>
        {finding.reasons.some((r) => humanizeReason(r) !== r) && (
          <TechnicalDetails summary="Raw reason data" className="mt-2">
            <ul className="flex flex-col gap-1">
              {finding.reasons.map((reason, i) => (
                <li key={i} className="font-data text-caption text-text-2">
                  {reason}
                </li>
              ))}
            </ul>
          </TechnicalDetails>
        )}
      </div>

      {finding.evidence_refs.length > 0 && (
        <div className="mb-4">
          <div className="mb-1.5 flex items-center gap-1.5">
            <h3 className="text-label text-text-2">Recovered frames</h3>
            <InfoHint label="Every recovered frame links back to its exact bytes on disk. A few are shown here as samples; the full list is in Technical details." />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {sampleRefs.map((ref) => (
              <Link
                key={ref}
                to="/cases/$cid/frames/$fid/prove"
                params={{ cid, fid: ref }}
                className="focus-ring flex items-center gap-1 rounded-full border border-line-strong bg-control px-2 py-0.5 font-data text-caption text-text-2 transition-colors hover:border-[color-mix(in_oklab,var(--brand-500)_40%,transparent)] hover:text-accent-text"
              >
                <Binary size={10} strokeWidth={1.75} />
                {ref.length > 14 ? `${ref.slice(0, 10)}…` : ref}
                <ChevronRight size={10} strokeWidth={1.75} />
              </Link>
            ))}
            {moreRefs > 0 && (
              <span className="rounded-full border border-line-strong bg-control px-2 py-0.5 text-caption text-text-3">
                +{moreRefs} more
              </span>
            )}
          </div>
          {moreRefs > 0 && (
            <TechnicalDetails summary={`All ${finding.evidence_refs.length} evidence references`} className="mt-2">
              <div className="flex flex-wrap gap-1.5">
                {finding.evidence_refs.map((ref) => (
                  <Link
                    key={ref}
                    to="/cases/$cid/frames/$fid/prove"
                    params={{ cid, fid: ref }}
                    className="focus-ring rounded border border-line-strong px-1.5 py-0.5 font-data text-caption text-text-2 hover:text-accent-text"
                  >
                    {ref}
                  </Link>
                ))}
              </div>
            </TechnicalDetails>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button asChild size="sm">
          <Link to="/cases/$cid/frames/$fid/prove" params={{ cid, fid: finding.evidence_refs[0] ?? finding.image_id }}>
            <Binary size={13} strokeWidth={1.75} />
            Prove it
          </Link>
        </Button>
        <Button asChild size="sm" variant="secondary">
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

/**
 * A compact inline visual of where in the day a deletion window falls — a single 96px bar
 * representing 00:00-24:00 IST with the deletion window highlighted, so a reader gets a sense of
 * "when" without parsing two timestamps. Purely decorative-informational; the exact window is
 * still given in text (the stat grid's "Deletion window"/"Action time" and the finding headline).
 */
function DeletionWindowBar({ startUs, endUs }: { startUs: number; endUs: number }) {
  const istOffsetUs = 5.5 * 3600 * 1_000_000;
  const dayUs = 24 * 3600 * 1_000_000;
  const dayStartUs = Math.floor((startUs + istOffsetUs) / dayUs) * dayUs - istOffsetUs;
  const pct = (us: number) => Math.min(100, Math.max(0, ((us - dayStartUs) / dayUs) * 100));
  const left = pct(startUs);
  const width = Math.max(0.8, pct(endUs) - left);
  return (
    <span
      className="relative inline-block h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-control align-middle"
      title="Position of the deletion window within the day (IST)"
      aria-hidden
    >
      <span className="absolute inset-y-0 rounded-full bg-recovered" style={{ left: `${left}%`, width: `${width}%` }} />
    </span>
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
