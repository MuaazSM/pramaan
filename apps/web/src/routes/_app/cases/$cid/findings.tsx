/** /cases/$cid/findings — Findings. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { ShieldAlert } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/findings")({
  component: FindingsPlaceholder,
});

function FindingsPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Findings" }]}
        caseId={cid}
        icon={ShieldAlert}
        title="Findings"
        description="Deletion verdict cards: method, range, actor, confidence meter, and a reasons list that cites offsets and log ids — every finding links back to the timeline and Prove it."
        owner="WEB (Wave 3)"
      />
    );
}
