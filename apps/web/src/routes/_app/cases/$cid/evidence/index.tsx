/** /cases/$cid/evidence — Evidence list. Designed placeholder for this wave; full build is a later WEB task. */
import { createFileRoute } from "@tanstack/react-router";
import { HardDrive } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/evidence/")({
  component: EvidenceListPlaceholder,
});

function EvidenceListPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Evidence" }]}
        caseId={cid}
        icon={HardDrive}
        title="Evidence"
        description="A virtualised table of every registered image with tier, integrity and scan state. Use Add evidence from the case overview to register the first image."
        owner="WEB (Wave 2)"
      />
    );
}
