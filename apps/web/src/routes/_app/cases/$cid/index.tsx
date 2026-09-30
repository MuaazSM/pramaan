/**
 * /cases/$cid — Case overview.
 * Primary action: Add evidence (or Open review once evidence has been scanned).
 * Reference products studied: Linear (project overview cards + stat row), Vercel (deployment
 * summary tone, calm numbers).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Plus, PlaySquare, HardDrive, ShieldAlert, Clock3, Radio, Sparkles } from "lucide-react";
import { ScreenShell } from "@/components/shell/screen-shell";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { InfoHint } from "@/components/ui/info-hint";
import { TechnicalDetails } from "@/components/ui/technical-details";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { TierBadge, type Tier } from "@/components/signature/tier-badge";
import { formatBytes, formatTimecode } from "@/lib/format";
import { fileName, GLOSSARY } from "@/lib/humanize";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";

export const Route = createFileRoute("/_app/cases/$cid/")({
  component: CaseOverviewScreen,
});

function CaseOverviewScreen() {
  const { cid } = Route.useParams();

  const caseQuery = useQuery({
    queryKey: ["case", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}", { params: { path: { cid } } });
      if (error || !data) throw errorFromResponse(response, "this case could not be loaded");
      return data;
    },
  });
  const evidenceQuery = useQuery({
    queryKey: ["evidence", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/evidence", { params: { path: { cid } } });
      if (error) throw errorFromResponse(response, "evidence could not be loaded");
      return data ?? [];
    },
  });
  const deletionsQuery = useQuery({
    queryKey: ["deletions", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/deletions", { params: { path: { cid } } });
      if (error) throw errorFromResponse(response, "deletions could not be loaded");
      return data ?? [];
    },
  });
  const clocksQuery = useQuery({
    queryKey: ["clock-models", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/clock-models", { params: { path: { cid } } });
      if (error) throw errorFromResponse(response, "clock models could not be loaded");
      return data ?? [];
    },
  });
  const recordingsQuery = useQuery({
    queryKey: ["recordings", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/recordings", { params: { path: { cid } } });
      if (error) throw errorFromResponse(response, "recordings could not be loaded");
      return data ?? [];
    },
  });
  const auditQuery = useQuery({
    queryKey: ["audit", cid, "recent"],
    queryFn: async () => (await api.GET("/api/cases/{cid}/audit", { params: { path: { cid }, query: { limit: 6 } } })).data,
  });

  const c = caseQuery.data;
  const evidence = evidenceQuery.data ?? [];
  const deletions = deletionsQuery.data ?? [];
  const clocks = clocksQuery.data ?? [];
  const recordings = recordingsQuery.data ?? [];
  const channels = new Set(recordings.map((r) => r.channel)).size;
  const recoveredSeconds = deletions.reduce((sum, d) => sum + (d.end_ts_us - d.start_ts_us) / 1_000_000, 0);
  const avgConfidence = clocks.length ? clocks.reduce((s, c2) => s + c2.confidence, 0) / clocks.length : null;
  const allVerified = evidence.length > 0 && evidence.every((e) => e.verified);

  // A failed *case* fetch (401/403/404/network/500) means nothing below it — evidence, findings,
  // recovered-footage totals — can be trusted either, so the whole screen shows one classified
  // error instead of a permanently-stuck skeleton (the old `caseQuery.isLoading || !c` condition
  // never resolved on error: isLoading goes false, but `c` stays undefined forever) or, worse,
  // silently rendering the other panels' empty states as if the case genuinely had zero evidence.
  if (caseQuery.isError) {
    return (
      <ScreenShell segments={[{ label: "Cases", to: "/cases" }, { label: cid }]} caseId={cid}>
        <QueryErrorState error={caseQuery.error} subject="this case" onRetry={() => void caseQuery.refetch()} />
      </ScreenShell>
    );
  }

  return (
    <ScreenShell
      segments={[{ label: "Cases", to: "/cases" }, { label: c?.case_number ?? cid }]}
      caseId={cid}
      showCustodySeal
    >
      <div className="mx-auto flex max-w-6xl flex-col gap-8 p-6">
        {caseQuery.isLoading || !c ? (
          <Skeleton className="h-20 w-full" />
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-page-title text-text">{c.title}</h1>
                <Badge variant={c.status === "open" ? "ok" : "neutral"} className="capitalize">
                  {c.status}
                </Badge>
              </div>
              {/* F6: case number/FIR/lab are each their own datum, not a dot-joined sentence —
                  case_number and fir_reference are IDs (mono), lab is a plain name (sans). */}
              <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-label text-text-2">
                <span className="font-data">{c.case_number}</span>
                {c.fir_reference && <span className="font-data">{c.fir_reference}</span>}
                {c.lab && <span>{c.lab}</span>}
              </p>
            </div>
            <div className="flex gap-2">
              {evidence.length > 0 ? (
                <Button asChild>
                  <Link to="/cases/$cid/review" params={{ cid }}>
                    <PlaySquare size={15} strokeWidth={1.75} />
                    Open review
                  </Link>
                </Button>
              ) : (
                <Button asChild>
                  <Link to="/cases/$cid/evidence/new" params={{ cid }}>
                    <Plus size={15} strokeWidth={1.75} />
                    Add evidence
                  </Link>
                </Button>
              )}
            </div>
          </div>
        )}

        {/* "What we found" — the 30-second summary (F7: story first, bytes on demand). A plain
            sentence built from the same structured fields the stat row below shows as numbers,
            so a first-time viewer gets the story before the data. */}
        {!caseQuery.isLoading && c && (
          <div className="rounded-[var(--radius-card)] border border-line bg-panel p-4">
            <div className="mb-1.5 flex items-center gap-1.5">
              <Sparkles size={13} strokeWidth={1.75} className="text-accent-text" />
              <h2 className="text-section text-text">What we found</h2>
            </div>
            <p className="text-base text-text-2">
              {evidence.length === 0 ? (
                "No evidence has been registered for this case yet."
              ) : (
                <>
                  {evidenceQuery.isLoading || deletionsQuery.isLoading || recordingsQuery.isLoading || clocksQuery.isLoading
                    ? "Loading a summary of this case…"
                    : caseSummarySentence({ evidenceCount: evidence.length, channels, deletionCount: deletions.length, recoveredSeconds, avgConfidence, allVerified })}
                </>
              )}
            </p>
          </div>
        )}

        {/* Integrity summary */}
        <div className="rounded-[var(--radius-card)] border border-line bg-panel p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <h2 className="text-section text-text">Integrity summary</h2>
              <InfoHint label="Every evidence image's hash is re-computed and compared to the one recorded at acquisition. 'Verified' means the bytes have not changed since." />
            </div>
            {evidence.length > 0 && (
              <Badge variant={allVerified ? "ok" : "warn"}>{allVerified ? "all verified" : "verification pending"}</Badge>
            )}
          </div>
          {evidenceQuery.isLoading ? (
            <Skeleton className="h-8 w-full" />
          ) : evidenceQuery.isError ? (
            <QueryErrorState error={evidenceQuery.error} subject="evidence" onRetry={() => void evidenceQuery.refetch()} className="py-4" />
          ) : evidence.length === 0 ? (
            <EmptyEvidence cid={cid} />
          ) : (
            <div className="flex flex-col items-start gap-2">
              {evidence.map((e) => (
                <div key={e.id} className="flex flex-wrap items-center gap-2">
                  <span className="min-w-[9rem] truncate text-label text-text-2" title={e.path}>
                    {fileName(e.path)}
                  </span>
                  <IntegrityChip state={e.verified ? "verified" : "pending"} hash={e.sha256} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Key numbers */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {/* "—" (not "0") whenever the backing query errored — a real zero and "the request
              failed so we don't actually know" must never look the same in a forensic summary. */}
          <StatCard icon={Radio} label="Channels" hint={GLOSSARY.channels} value={recordingsQuery.isError ? "—" : channels || "—"} />
          <StatCard
            icon={ShieldAlert}
            label="Deletion events"
            hint={GLOSSARY["deletion event"]}
            value={deletionsQuery.isError ? "—" : deletions.length}
          />
          <StatCard
            icon={Clock3}
            label="Recovered footage"
            hint={GLOSSARY["recovered footage"]}
            value={deletionsQuery.isError ? "—" : `${Math.round(recoveredSeconds / 60)} min`}
          />
          <StatCard
            icon={HardDrive}
            label="Clock confidence"
            hint={GLOSSARY["clock confidence"]}
            value={clocksQuery.isError ? "—" : avgConfidence != null ? `${Math.round(avgConfidence * 100)}%` : "—"}
          />
        </div>

        {/* Evidence cards */}
        <div>
          <h2 className="mb-3 text-section text-text">Evidence</h2>
          {evidenceQuery.isLoading ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-28 w-full" />
            </div>
          ) : evidence.length === 0 ? null : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {evidence.map((e) => (
                <EvidenceCard key={e.id} evidenceId={e.id} cid={cid} sha256={e.sha256} verified={e.verified} path={e.path} size={e.size_bytes} />
              ))}
            </div>
          )}
        </div>

        {/* Recent audit entries */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-section text-text">Recent audit entries</h2>
            <Link to="/cases/$cid/custody" params={{ cid }} className="focus-ring rounded text-sm text-accent-text hover:underline">
              View custody chain
            </Link>
          </div>
          {auditQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <ul className="flex flex-col divide-y divide-line rounded-[var(--radius-card)] border border-line">
              {auditQuery.data?.items.map((entry) => (
                <li key={entry.seq} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                  <span className="font-data tabular-nums text-text-3">#{entry.seq}</span>
                  <span className="text-text">{entry.action.replace(/\./g, " › ")}</span>
                  <span className="font-data text-text-3">{entry.object_type}/{entry.object_id}</span>
                  <span className="ml-auto text-text-2">{entry.actor}</span>
                  <span className="font-data tabular-nums text-text-3">{formatTimecode(entry.ts_utc)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </ScreenShell>
  );
}

/** The case overview's 30-second story, built entirely from fields the stat row already has. */
function caseSummarySentence({
  evidenceCount,
  channels,
  deletionCount,
  recoveredSeconds,
  avgConfidence,
  allVerified,
}: {
  evidenceCount: number;
  channels: number;
  deletionCount: number;
  recoveredSeconds: number;
  avgConfidence: number | null;
  allVerified: boolean;
}): string {
  const evidencePart = `${evidenceCount} evidence ${evidenceCount === 1 ? "image was" : "images were"} examined${channels > 0 ? ` across ${channels} camera channel${channels === 1 ? "" : "s"}` : ""}.`;
  const deletionPart =
    deletionCount === 0
      ? " No deletions were found."
      : ` ${deletionCount} deletion event${deletionCount === 1 ? "" : "s"} ${deletionCount === 1 ? "was" : "were"} found, and about ${Math.max(1, Math.round(recoveredSeconds / 60))} minute${Math.round(recoveredSeconds / 60) === 1 ? "" : "s"} of footage was recovered from deleted space.`;
  const clockPart =
    avgConfidence != null
      ? avgConfidence >= 0.85
        ? " Recovered timestamps are reliable."
        : " Some recovered timestamps have low confidence and may need examiner confirmation."
      : "";
  const integrityPart = allVerified ? " All evidence hashes are verified." : " Some evidence is still awaiting hash verification.";
  return `${evidencePart}${deletionPart}${clockPart}${integrityPart}`;
}

function StatCard({
  icon: Icon,
  label,
  hint,
  value,
}: {
  icon: typeof Radio;
  label: string;
  hint?: string;
  value: string | number;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-card p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-text-3">
        <Icon size={13} strokeWidth={1.75} />
        <span className="text-caption">{label}</span>
        {hint && <InfoHint label={hint} />}
      </div>
      <p className="tabular-nums text-xl font-semibold text-text">{value}</p>
    </div>
  );
}

function EvidenceCard({
  evidenceId,
  cid,
  sha256,
  verified,
  path,
  size,
}: {
  evidenceId: string;
  cid: string;
  sha256: string;
  verified: boolean;
  path: string;
  size: number;
}) {
  const fpQuery = useQuery({
    queryKey: ["fingerprint", evidenceId],
    queryFn: async () => (await api.GET("/api/evidence/{eid}/fingerprint", { params: { path: { eid: evidenceId } } })).data ?? [],
  });
  const match = fpQuery.data?.[0];

  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-line bg-card p-3 transition-colors hover:border-line-strong">
      <Link to="/cases/$cid/evidence/$eid" params={{ cid, eid: evidenceId }} className="focus-ring flex flex-col gap-2 rounded-[var(--radius-control)]">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-base font-medium text-text" title={path}>
            {fileName(path)}
          </span>
          {match && (
            <span title={GLOSSARY.tier}>
              <TierBadge tier={match.tier as Tier} />
            </span>
          )}
        </div>
        {/* One key fact in plain words, not raw identification-reason strings — the technical
            match reasons stay on the evidence-detail screen's Identification panel. */}
        <p className="truncate text-sm text-text-2">{match?.display_name ?? "Identifying…"}</p>
        <div className="flex items-center justify-between gap-2">
          <IntegrityChip state={verified ? "verified" : "pending"} hash={sha256} />
          <span className="font-data tabular-nums text-caption text-text-3">{formatBytes(size)}</span>
        </div>
      </Link>
      <TechnicalDetails summary="Technical details">
        <dl className="grid grid-cols-1 gap-1.5">
          <div>
            <dt className="text-label text-text-3">Full path</dt>
            <dd className="truncate font-data text-caption text-text-2" title={path}>
              {path}
            </dd>
          </div>
          <div>
            <dt className="text-label text-text-3">Evidence ID</dt>
            <dd className="font-data text-caption text-text-2">{evidenceId}</dd>
          </div>
        </dl>
      </TechnicalDetails>
    </div>
  );
}

function EmptyEvidence({ cid }: { cid: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <HardDrive size={24} strokeWidth={1.5} className="text-text-3" />
      <p className="text-base text-text-2">No evidence registered yet.</p>
      <Button size="sm" asChild>
        <Link to="/cases/$cid/evidence/new" params={{ cid }}>
          <Plus size={14} strokeWidth={1.75} />
          Add evidence
        </Link>
      </Button>
    </div>
  );
}
