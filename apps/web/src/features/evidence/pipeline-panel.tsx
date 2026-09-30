import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlayCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { JobLog } from "@/components/signature/job-log";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/api/client";
import { formatTimecode } from "@/lib/format";
import { useJobPipeline } from "./use-job-pipeline";

const STATUS_VARIANT = { queued: "neutral", running: "warn", done: "ok", failed: "danger" } as const;

/**
 * Scan pipeline progress, bound to `/api/ws` (see `use-job-pipeline.ts`). Primary action for the
 * evidence detail screen: "Run scan". Every state designed: empty (never scanned), queued,
 * running (live), done, failed.
 */
export function PipelinePanel({ cid, eid }: { cid: string; eid: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const jobsQuery = useQuery({
    queryKey: ["jobs", cid],
    queryFn: async () => (await api.GET("/api/cases/{cid}/jobs", { params: { path: { cid } } })).data ?? [],
    refetchInterval: 4000,
  });

  const evidenceJobs = (jobsQuery.data ?? []).filter((j) => j.evidence_id === eid);
  const activeJob = evidenceJobs.find((j) => j.status === "running" || j.status === "queued") ?? evidenceJobs[evidenceJobs.length - 1];
  const pipeline = useJobPipeline(cid, activeJob);

  const scanMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/evidence/{eid}/scan", { params: { path: { eid } }, body: { options: {} } });
      if (error || !data) throw new Error("scan failed");
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs", cid] });
      toast({ title: "Scan started", description: "Hash verify, identify, carve, timeline and custody stages will run in order." });
    },
    onError: () => {
      toast({ title: "Could not start scan", description: "Check your role — reviewers cannot run scans.", variant: "danger" });
    },
  });

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-panel p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-section text-text">Scan pipeline</h2>
        <div className="flex items-center gap-2">
          {activeJob && <Badge variant={STATUS_VARIANT[pipeline?.status ?? activeJob.status]}>{pipeline?.status ?? activeJob.status}</Badge>}
          <Button size="sm" onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending || pipeline?.status === "running"}>
            <PlayCircle size={14} strokeWidth={1.75} />
            Run scan
          </Button>
        </div>
      </div>

      {jobsQuery.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !activeJob ? (
        <EmptyPipeline />
      ) : (
        <div className="flex flex-col gap-2">
          <JobLog stages={pipeline?.stages ?? activeJob.stages} logLines={pipeline?.logLines ?? activeJob.log_lines} pct={pipeline?.pct ?? activeJob.pct} />
          <p className="text-right font-data text-caption text-text-3">updated {formatTimecode(activeJob.updated_utc)}</p>
        </div>
      )}
    </section>
  );
}

function EmptyPipeline() {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <PlayCircle size={20} strokeWidth={1.5} className="text-text-3" />
      <p className="text-base text-text-2">This image has not been scanned yet.</p>
      <p className="text-sm text-text-3">Run scan to hash-verify, identify, carve and build the timeline.</p>
    </div>
  );
}
