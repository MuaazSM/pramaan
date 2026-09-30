/**
 * /cases/$cid/recordings — Recordings. See src/features/recordings/recordings-screen.tsx for the
 * screen brief and reference products studied.
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { RecordingsScreen } from "@/features/recordings/recordings-screen";

export const Route = createFileRoute("/_app/cases/$cid/recordings")({
  component: RecordingsRoute,
});

function RecordingsRoute() {
  const { cid } = Route.useParams();
  return (
    <ScreenShell segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Recordings" }]} caseId={cid} showCustodySeal>
      <RecordingsScreen cid={cid} />
    </ScreenShell>
  );
}
