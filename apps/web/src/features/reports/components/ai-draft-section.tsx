import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AIDraftBlock, type AiSentence } from "@/components/signature/ai-draft-block";
import { api } from "@/api/client";
import { buildReportFacts } from "../lib/build-facts";
import { csrfHeaders } from "../lib/csrf";
import type { ReportRecord } from "../lib/manifest";
import { useReportManifest } from "./manifest-view";

type Decision = "pending" | "accepted" | "rejected";

/**
 * "AI draft — narrative summary". Rendered only when the server reports `llm_enabled === true`
 * (GET /system/health); otherwise it renders nothing at all — no disabled button, no placeholder —
 * so a build with the LLM off can never show anything that looks like a drafted finding
 * (CLAUDE.md rule 6). Uses the same ["health"] query key as the settings screen.
 */
export function AiDraftSection({ caseId, report }: { caseId: string; report: ReportRecord | undefined }) {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.GET("/api/system/health")).data,
  });
  if (health.data?.llm_enabled !== true || !report) return null;
  return <AiDraftPanel caseId={caseId} report={report} />;
}

function AiDraftPanel({ caseId, report }: { caseId: string; report: ReportRecord }) {
  const manifest = useReportManifest(report.id);
  const facts = useMemo(() => (manifest.data ? buildReportFacts(manifest.data, report) : []), [manifest.data, report]);
  const [sentences, setSentences] = useState<AiSentence[] | null>(null);
  const [decision, setDecision] = useState<Decision>("pending");

  const draft = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/cases/{cid}/assistant/draft", {
        params: { path: { cid: caseId } },
        body: { facts },
        headers: csrfHeaders(),
      });
      if (error || !data) throw new Error("draft failed");
      return data.map((s) => ({ text: s.text, evidenceIds: s.evidence_ids }));
    },
    onSuccess: (s) => {
      setSentences(s);
      setDecision("pending");
    },
  });

  return (
    <section
      aria-labelledby="ai-draft-heading"
      className="rounded-[var(--radius-panel)] border border-line bg-panel p-5"
      data-testid="ai-draft-section"
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-xl">
          <h2 id="ai-draft-heading" className="flex items-center gap-2 text-[14px] font-semibold text-text">
            <Sparkles size={15} strokeWidth={1.75} className="text-ai" />
            AI draft — narrative summary
          </h2>
          <p className="mt-1 text-[12px] text-text-2">
            Drafted only from structured facts in the latest report's manifest. No frames, thumbnails or disk bytes are
            sent. A draft is never a finding; every sentence cites the fact it rests on.
          </p>
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => draft.mutate()}
          disabled={draft.isPending || facts.length === 0}
        >
          <Sparkles size={14} strokeWidth={1.75} />
          {sentences ? "Draft again" : "Draft narrative"}
        </Button>
      </div>

      {manifest.isLoading && <Skeleton className="h-16 w-full" />}
      {manifest.isError && (
        <p role="alert" className="text-[12px] text-text-2">
          Couldn't load the manifest this draft would be built from.
        </p>
      )}
      {draft.isPending && <Skeleton className="h-24 w-full" />}
      {draft.isError && (
        <div role="alert" className="flex items-center gap-2 rounded-[var(--radius-card)] border border-line bg-card p-3 text-[12px] text-text-2">
          <AlertTriangle size={14} strokeWidth={1.75} className="text-danger" />
          The draft could not be produced. Nothing was added to the report.
        </div>
      )}

      {sentences && !draft.isPending && decision !== "rejected" && (
        <div className="flex flex-col gap-2">
          <AIDraftBlock
            sentences={sentences}
            onAccept={() => setDecision("accepted")}
            onReject={() => setDecision("rejected")}
            className={decision === "accepted" ? "border-solid" : undefined}
          />
          {decision === "accepted" && (
            <p className="text-[12px] text-text-2" data-testid="ai-draft-accepted-note">
              Marked accepted in this session only. Acceptance is not saved to the report yet, so it will not appear in
              the PDF or manifest.
            </p>
          )}
        </div>
      )}
      {decision === "rejected" && !draft.isPending && (
        <p className="text-[12px] text-text-2">Draft rejected. Nothing was added to the report.</p>
      )}

      {facts.length > 0 && (
        <details className="mt-3 text-[12px] text-text-2">
          <summary className="cursor-pointer select-none text-text-3 hover:text-text-2">
            {`Facts sent to the assistant (${facts.length})`}
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {facts.map((f) => (
              <li key={f.id} className="flex gap-2">
                <span className="shrink-0 font-mono text-[11px] text-text-3">{f.id}</span>
                <span>{f.text}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
