/**
 * /cases/$cid/review — Review workspace (hero screen).
 * Primary action: play / jump to time.
 * Reference products studied: Frame.io (player chrome, frame-accurate scrubbing), DaVinci
 * Resolve (multi-track synced timeline, zoomable ruler, track headers), Grafana (dense
 * time-series brushing for the motion strip).
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { ReviewWorkspace } from "@/features/review/review-workspace";

export const Route = createFileRoute("/_app/cases/$cid/review")({
  component: ReviewRoute,
});

function ReviewRoute() {
  const { cid } = Route.useParams();
  return (
    <ScreenShell
      segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Review" }]}
      caseId={cid}
      showCustodySeal={true}
    >
      <ReviewWorkspace caseId={cid} />
    </ScreenShell>
  );
}
