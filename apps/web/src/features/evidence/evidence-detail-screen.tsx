/**
 * /cases/$cid/evidence/$eid — Evidence detail.
 * Primary action: Run scan (in the pipeline panel).
 * Reference products studied: Sentry (stacked context panels, issue-detail layout), Vercel
 * (deployment-log-style pipeline progress, calm monochrome stat rows).
 */
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { formatBytes, formatTimecode } from "@/lib/format";
import { IdentificationPanel } from "./identification-panel";
import { PipelinePanel } from "./pipeline-panel";
import { InferredLayoutPanel } from "./inferred-layout-panel";
import { DeviceLogTable } from "./device-log-table";

export function EvidenceDetailScreen({ cid, eid }: { cid: string; eid: string }) {
  const evidenceQuery = useQuery({
    queryKey: ["evidence-detail", eid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/evidence/{eid}", { params: { path: { eid } } });
      if (error || !data) throw errorFromResponse(response, "this evidence image could not be loaded");
      return data;
    },
  });

  if (evidenceQuery.isLoading) {
    return (
      <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (evidenceQuery.isError || !evidenceQuery.data) {
    return (
      <QueryErrorState
        error={evidenceQuery.error}
        subject="this evidence image"
        onRetry={() => void evidenceQuery.refetch()}
        className="py-20"
      />
    );
  }

  const e = evidenceQuery.data;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {/* File path is evidence data (BRAND.md §4 lists file paths alongside hashes/offsets) —
              mono, sized as a page title since this is the screen's one identifying heading. */}
          <h1 className="truncate font-data text-lg font-semibold text-text">{e.path}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-label text-text-2">
            <Badge variant="neutral">{e.format}</Badge>
            <span className="font-data">{formatBytes(e.size_bytes)}</span>
            <span>acquired <span className="font-data">{formatTimecode(e.acquired_utc)}</span></span>
          </div>
        </div>
        <IntegrityChip state={e.verified ? "verified" : "pending"} hash={e.sha256} />
      </div>

      <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-line bg-card px-3 py-2 text-label text-text-2">
        <ShieldCheck size={13} strokeWidth={1.75} className="shrink-0 text-text-3" />
        MD5 <span className="font-data text-text">{e.md5}</span>
      </div>

      <IdentificationPanel eid={eid} />
      <PipelinePanel cid={cid} eid={eid} />
      <InferredLayoutPanel eid={eid} />
      <DeviceLogTable cid={cid} eid={eid} />
    </div>
  );
}
