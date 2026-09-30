/**
 * /cases/$cid/evidence/$eid — Evidence detail.
 * Primary action: Run scan (in the pipeline panel).
 * Reference products studied: Sentry (stacked context panels, issue-detail layout), Vercel
 * (deployment-log-style pipeline progress, calm monochrome stat rows).
 */
import { useQuery } from "@tanstack/react-query";
import { HardDrive, ShieldCheck } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { api } from "@/api/client";
import { formatBytes, formatTimecode } from "@/lib/format";
import { IdentificationPanel } from "./identification-panel";
import { PipelinePanel } from "./pipeline-panel";
import { InferredLayoutPanel } from "./inferred-layout-panel";
import { DeviceLogTable } from "./device-log-table";

export function EvidenceDetailScreen({ cid, eid }: { cid: string; eid: string }) {
  const evidenceQuery = useQuery({
    queryKey: ["evidence-detail", eid],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/evidence/{eid}", { params: { path: { eid } } });
      if (error || !data) throw new Error("evidence not found");
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
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <HardDrive size={24} strokeWidth={1.5} className="text-text-3" />
        <p className="text-[13px] text-text-2">This evidence image could not be found.</p>
      </div>
    );
  }

  const e = evidenceQuery.data;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate font-mono text-[16px] font-semibold text-text">{e.path}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-2">
            <Badge variant="neutral" className="uppercase">{e.format}</Badge>
            <span>{formatBytes(e.size_bytes)}</span>
            <span className="text-text-3">·</span>
            <span>acquired {formatTimecode(e.acquired_utc)}</span>
          </div>
        </div>
        <IntegrityChip state={e.verified ? "verified" : "pending"} hash={e.sha256} />
      </div>

      <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-line bg-card px-3 py-2 text-xs text-text-2">
        <ShieldCheck size={13} strokeWidth={1.75} className="shrink-0 text-text-3" />
        MD5 <span className="font-mono text-text">{e.md5}</span>
      </div>

      <IdentificationPanel eid={eid} />
      <PipelinePanel cid={cid} eid={eid} />
      <InferredLayoutPanel eid={eid} />
      <DeviceLogTable cid={cid} eid={eid} />
    </div>
  );
}
