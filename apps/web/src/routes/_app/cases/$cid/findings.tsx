/**
 * /cases/$cid/findings — Findings. See src/features/findings/findings-screen.tsx for the screen
 * brief and reference products studied.
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { FindingsScreen } from "@/features/findings/findings-screen";

export const Route = createFileRoute("/_app/cases/$cid/findings")({
  component: FindingsRoute,
});

function FindingsRoute() {
  const { cid } = Route.useParams();
  return (
    <ScreenShell segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Findings" }]} caseId={cid} showCustodySeal>
      <FindingsScreen cid={cid} />
    </ScreenShell>
  );
}
