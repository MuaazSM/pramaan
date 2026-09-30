/**
 * /cases/$cid/evidence/$eid — Evidence detail. See src/features/evidence/evidence-detail-screen.tsx
 * for the screen brief and reference products studied.
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { EvidenceDetailScreen } from "@/features/evidence/evidence-detail-screen";
import { useCaseLabel, useEvidenceLabel } from "@/api/labels";

export const Route = createFileRoute("/_app/cases/$cid/evidence/$eid")({
  component: EvidenceDetailRoute,
});

function EvidenceDetailRoute() {
  const { cid, eid } = Route.useParams();
  const caseLabel = useCaseLabel(cid);
  const evidenceLabel = useEvidenceLabel(eid);
  return (
    <ScreenShell
      segments={[
        { label: "Cases", to: "/cases" },
        { label: caseLabel, to: `/cases/${cid}` },
        { label: "Evidence", to: `/cases/${cid}/evidence` },
        { label: evidenceLabel },
      ]}
      caseId={cid}
      showCustodySeal
    >
      <EvidenceDetailScreen cid={cid} eid={eid} />
    </ScreenShell>
  );
}
