/**
 * /cases/$cid/custody — Custody chain.
 * Primary action: Re-verify chain. Hash-chained audit timeline (cursor-paginated), verification
 * result, and Merkle anchors (local / Fabric) with create-anchor.
 * Reference products studied: Sentry (event breadcrumbs / timeline of events in an issue detail).
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { CustodyScreen } from "@/features/custody/custody-screen";
import { useCaseLabel } from "@/api/labels";

export const Route = createFileRoute("/_app/cases/$cid/custody")({
  component: CustodyRoute,
});

function CustodyRoute() {
  const { cid } = Route.useParams();
  const caseLabel = useCaseLabel(cid);
  return (
    <ScreenShell
      segments={[{ label: "Cases", to: "/cases" }, { label: caseLabel, to: `/cases/${cid}` }, { label: "Custody" }]}
      caseId={cid}
      showCustodySeal
    >
      <CustodyScreen caseId={cid} />
    </ScreenShell>
  );
}
