/** /cases/$cid/evidence — Evidence list. Designed placeholder for this wave; full build is a later WEB task. */
import { createFileRoute } from "@tanstack/react-router";
import { HardDrive } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";
import { useCaseLabel } from "@/api/labels";

export const Route = createFileRoute("/_app/cases/$cid/evidence/")({
  component: EvidenceListPlaceholder,
});

function EvidenceListPlaceholder() {
    const { cid } = Route.useParams();
    const caseLabel = useCaseLabel(cid);
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: caseLabel, to: `/cases/${cid}` }, { label: "Evidence" }]}
        caseId={cid}
        icon={HardDrive}
        title="Evidence"
        description="A virtualised table of every registered image with tier, integrity and scan state. Use Add evidence from the case overview to register the first image."
        owner="WEB (Wave 2)"
      />
    );
}
