import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/**
 * Breadcrumb-label resolvers — fixes the orchestrator UI-QA item "breadcrumbs show raw ids
 * (case_cr20260412, ev_hiksim01)". Works the same in mock and real mode: both fetch through the
 * typed client, MSW intercepts in mock mode exactly like every other query in this app (F1's
 * documented convention).
 *
 * Only used inside this task's own owned route files (reports/exports/custody/settings) — the
 * evidence-detail/review/recordings/findings/prove-it route files that also build breadcrumbs
 * with a raw id are owned by other, already-`done` WEB tasks (F2/F3a/F3b) and are out of this
 * task's paths.
 */

/** Resolves a case id to its human case number (`CR-2026-0412`), falling back to the raw id
 * while the fetch is in flight or if it 404s. */
export function useCaseLabel(caseId: string | undefined): string {
  const { data } = useQuery({
    queryKey: ["case-label", caseId],
    queryFn: async () => {
      const res = await api.GET("/api/cases/{cid}", { params: { path: { cid: caseId ?? "" } } });
      return res.data ?? null;
    },
    enabled: Boolean(caseId),
    staleTime: 5 * 60_000,
  });
  return data?.case_number ?? caseId ?? "";
}

/** Resolves an evidence id to a short, readable label (the acquired file's basename), falling
 * back to the raw id. */
export function useEvidenceLabel(evidenceId: string | undefined): string {
  const { data } = useQuery({
    queryKey: ["evidence-label", evidenceId],
    queryFn: async () => {
      const res = await api.GET("/api/evidence/{eid}", { params: { path: { eid: evidenceId ?? "" } } });
      return res.data ?? null;
    },
    enabled: Boolean(evidenceId),
    staleTime: 5 * 60_000,
  });
  if (!data) return evidenceId ?? "";
  const base = data.path.split("/").pop();
  return base || evidenceId || "";
}
