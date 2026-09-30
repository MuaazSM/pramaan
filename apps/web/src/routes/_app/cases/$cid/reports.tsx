/**
 * /cases/$cid/reports — Reports.
 * Primary action: Generate report. Report list with sha256 IntegrityChip, PDF / BSA §63
 * certificate links and a manifest key-row view; an "AI draft — narrative summary" block that
 * only exists when the server reports the LLM as enabled (always a labelled draft).
 * Reference products studied: Stripe (invoice list + download actions), Linear (dense, calm rows).
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { useCaseLabel } from "@/api/labels";
import { ReportsScreen } from "@/features/reports/reports-screen";

export const Route = createFileRoute("/_app/cases/$cid/reports")({
  component: ReportsRoute,
});

function ReportsRoute() {
  const { cid } = Route.useParams();
  const caseLabel = useCaseLabel(cid);
  return (
    <ScreenShell
      segments={[{ label: "Cases", to: "/cases" }, { label: caseLabel, to: `/cases/${cid}` }, { label: "Reports" }]}
      caseId={cid}
      showCustodySeal
    >
      <ReportsScreen caseId={cid} />
    </ScreenShell>
  );
}
