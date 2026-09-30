import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FilePlus2, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/api/client";
import { AiDraftSection } from "./components/ai-draft-section";
import { ReportCard } from "./components/report-card";
import { csrfHeaders } from "./lib/csrf";

/**
 * Indicative progress for a single synchronous request: eases towards 90% while the call is in
 * flight and never claims completion until the response arrives. Not a measured percentage and
 * not a set of pipeline stages — the endpoint has none to report.
 */
function useIndicativeProgress(active: boolean): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!active) return;
    const start = performance.now();
    const id = window.setInterval(() => {
      const t = (performance.now() - start) / 1000;
      setValue(Math.round(90 * (1 - Math.exp(-t / 1.5))));
    }, 120);
    return () => {
      window.clearInterval(id);
      setValue(0);
    };
  }, [active]);
  return value;
}

export function ReportsScreen({ caseId }: { caseId: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const reportsQuery = useQuery({
    queryKey: ["reports", caseId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cases/{cid}/reports", { params: { path: { cid: caseId } } });
      if (error || !data) throw new Error("reports unavailable");
      return data;
    },
  });

  const generate = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/cases/{cid}/reports", {
        params: { path: { cid: caseId } },
        body: { include_thumbnails: true },
        headers: csrfHeaders(),
      });
      if (error || !data) throw new Error("generate failed");
      return data;
    },
    onSuccess: async (report) => {
      await queryClient.invalidateQueries({ queryKey: ["reports", caseId] });
      toast({
        title: "Report generated",
        description: `${report.id} · sha256 ${report.report_sha256.slice(0, 12)}…`,
        variant: "ok",
      });
    },
    onError: () => {
      toast({
        title: "Could not generate the report",
        description: "Check your role — reviewers cannot generate reports.",
        variant: "danger",
      });
    },
  });
  const progress = useIndicativeProgress(generate.isPending);

  // Newest first; id breaks ties so the order is stable.
  const reports = [...(reportsQuery.data ?? [])].sort(
    (a, b) => b.created_utc.localeCompare(a.created_utc) || b.id.localeCompare(a.id),
  );

  const generateButton = (
    <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
      <FilePlus2 size={14} strokeWidth={1.75} />
      {generate.isPending ? "Generating…" : "Generate report"}
    </Button>
  );

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">Reports</h1>
          <p className="text-[13px] text-text-2">
            Each report freezes the case into a hashed manifest, a PDF and a BSA §63 certificate template.
          </p>
        </div>
        {generateButton}
      </div>

      {generate.isPending && (
        <div role="status" className="rounded-[var(--radius-card)] border border-line bg-panel p-3" data-testid="generate-progress">
          <div className="mb-2 flex items-center justify-between text-[12px]">
            <span className="text-text">Generating report on the server…</span>
            <span className="font-mono tabular-nums text-text-3">{progress}%</span>
          </div>
          <Progress value={progress} aria-label="Report generation (indicative)" />
          <p className="mt-2 text-[11px] text-text-3">
            One request: the server hashes the manifest and renders the PDF and certificate, then returns. The bar is
            indicative, not a measured percentage.
          </p>
        </div>
      )}

      {reportsQuery.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : reportsQuery.isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 rounded-[var(--radius-panel)] border border-line bg-panel p-10 text-center">
          <AlertTriangle size={22} strokeWidth={1.5} className="text-danger" />
          <div>
            <p className="text-[13px] font-medium text-text">Couldn't load this case's reports</p>
            <p className="mt-1 text-[12px] text-text-2">The case may not exist, or the session may have expired.</p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => void reportsQuery.refetch()}>
            Try again
          </Button>
        </div>
      ) : reports.length === 0 ? (
        <EmptyReports action={generateButton} />
      ) : (
        <ul className="flex flex-col gap-3" aria-label="Generated reports">
          {reports.map((r, i) => (
            <ReportCard key={r.id} report={r} latest={i === 0} />
          ))}
        </ul>
      )}

      <AiDraftSection caseId={caseId} report={reports[0]} />

      <p className="text-[11px] text-text-3">
        The BSA §63 certificate is a template generated by Pramaan; verify its wording against the official Schedule
        before filing. Signature, name, designation and date lines are left blank for you to complete.
      </p>
    </div>
  );
}

function EmptyReports({ action }: { action: React.ReactNode }) {
  return (
    <div
      className="flex flex-col items-center gap-4 rounded-[var(--radius-panel)] border border-dashed border-line-strong bg-panel px-8 py-14 text-center"
      data-testid="reports-empty"
    >
      <div className="flex size-12 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
        <FileText size={22} strokeWidth={1.5} className="text-text-3" />
      </div>
      <div className="max-w-md">
        <h2 className="text-[16px] font-semibold text-text">No reports yet</h2>
        <p className="mt-1.5 text-[13px] text-text-2">
          Generate one when your review is complete. The report hash is computed from the manifest, so regenerating over
          unchanged data gives the same hash.
        </p>
      </div>
      {action}
    </div>
  );
}
