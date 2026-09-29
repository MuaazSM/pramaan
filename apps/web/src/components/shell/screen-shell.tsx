import { useQuery } from "@tanstack/react-query";
import { TopBar } from "@/components/shell/topbar";
import { CustodySeal } from "@/components/signature/custody-seal";
import type { LineageSegment } from "@/components/signature/lineage-breadcrumb";
import { api } from "@/api/client";

/**
 * Per-screen chrome: top bar (with this screen's lineage breadcrumb) + scrollable content +
 * an optional custody seal footer (case screens only, per docs/04-FRONTEND.md §4).
 */
export function ScreenShell({
  segments,
  caseId,
  showCustodySeal = false,
  children,
}: {
  segments: LineageSegment[];
  caseId?: string;
  showCustodySeal?: boolean;
  children: React.ReactNode;
}) {
  const { data: jobs } = useQuery({
    queryKey: ["jobs", caseId, "running"],
    queryFn: async () => {
      const { data } = await api.GET("/api/cases/{cid}/jobs", { params: { path: { cid: caseId! } } });
      return data ?? [];
    },
    enabled: Boolean(caseId),
    refetchInterval: 5000,
  });
  const runningJob = jobs?.find((j) => j.status === "running");

  const { data: verify } = useQuery({
    queryKey: ["audit-verify", caseId],
    queryFn: async () => {
      const { data } = await api.GET("/api/cases/{cid}/audit/verify", { params: { path: { cid: caseId! } } });
      return data;
    },
    enabled: Boolean(caseId) && showCustodySeal,
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar segments={segments} runningJob={runningJob} />
      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      {showCustodySeal && verify && (
        <CustodySeal
          ok={verify.ok}
          entryCount={verify.length}
          headHash={verify.head_hash ?? ""}
          anchoredAtIso="2026-03-18T08:52:00Z"
        />
      )}
    </div>
  );
}
