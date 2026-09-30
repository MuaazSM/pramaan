/**
 * /cases/$cid/evidence/$eid — Evidence detail. See src/features/evidence/evidence-detail-screen.tsx
 * for the screen brief and reference products studied.
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { EvidenceDetailScreen } from "@/features/evidence/evidence-detail-screen";

export const Route = createFileRoute("/_app/cases/$cid/evidence/$eid")({
  component: EvidenceDetailRoute,
});

function EvidenceDetailRoute() {
  const { cid, eid } = Route.useParams();
  return (
    <ScreenShell
      segments={[
        { label: "Cases", to: "/cases" },
        { label: cid, to: `/cases/${cid}` },
        { label: "Evidence", to: `/cases/${cid}/evidence` },
        { label: eid },
      ]}
      caseId={cid}
      showCustodySeal
    >
      <EvidenceDetailScreen cid={cid} eid={eid} />
    </ScreenShell>
  );
}
