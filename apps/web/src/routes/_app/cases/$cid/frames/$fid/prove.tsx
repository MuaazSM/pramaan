/**
 * /cases/$cid/frames/$fid/prove — "Prove it" hex view.
 * Primary action: Copy proof. Real screen (docs/progress/F3b.md) — see
 * src/features/prove/prove-view.tsx for the implementation; this file only owns route wiring and
 * the ScreenShell chrome, per F1's routing convention.
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { ProveView } from "@/features/prove/prove-view";
import { useCaseLabel } from "@/api/labels";

export const Route = createFileRoute("/_app/cases/$cid/frames/$fid/prove")({
  component: ProveScreen,
});

function ProveScreen() {
  const { cid, fid } = Route.useParams();
  const caseLabel = useCaseLabel(cid);
  return (
    <ScreenShell
      segments={[
        { label: "Cases", to: "/cases" },
        { label: caseLabel, to: `/cases/${cid}` },
        { label: "Review", to: `/cases/${cid}/review` },
        { label: `Frame ${fid}` },
      ]}
      caseId={cid}
      showCustodySeal
    >
      <ProveView caseId={cid} frameId={fid} />
    </ScreenShell>
  );
}
