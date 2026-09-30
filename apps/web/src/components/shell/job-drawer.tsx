import { useQuery } from "@tanstack/react-query";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { JobLog } from "@/components/signature/job-log";
import { Badge } from "@/components/ui/badge";
import { useUiStore } from "@/store/ui";
import { api } from "@/api/client";
import { formatTimecode } from "@/lib/format";

const STATUS_VARIANT = {
  queued: "neutral",
  running: "warn",
  done: "ok",
  failed: "danger",
} as const;

/** Right-side sheet listing running/finished jobs for the current case, Vercel-style build log. */
export function JobDrawer({ caseId }: { caseId?: string }) {
  const open = useUiStore((s) => s.jobDrawerOpen);
  const setOpen = useUiStore((s) => s.setJobDrawerOpen);

  const { data: jobs } = useQuery({
    queryKey: ["jobs", caseId],
    queryFn: async () => {
      const { data } = await api.GET("/api/cases/{cid}/jobs", { params: { path: { cid: caseId! } } });
      return data ?? [];
    },
    enabled: Boolean(caseId) && open,
    refetchInterval: open ? 4000 : false,
  });

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent aria-describedby={undefined}>
        <SheetHeader>
          <SheetTitle>Jobs</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto">
          {!jobs || jobs.length === 0 ? (
            <p className="py-8 text-center text-sm text-text-3">No jobs for this case yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {jobs.map((job) => (
                <li key={job.id} className="rounded-[var(--radius-card)] border border-line bg-card p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-base font-medium capitalize text-text">{job.kind}</span>
                      <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
                    </div>
                    <span className="font-data text-caption text-text-3">{formatTimecode(job.updated_utc)}</span>
                  </div>
                  <JobLog stages={job.stages} logLines={job.log_lines} pct={job.pct} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
