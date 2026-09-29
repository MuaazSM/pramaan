/** /cases/$cid/evidence/$eid — Evidence detail. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { ScanSearch } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/evidence/$eid")({
  component: EvidenceDetailPlaceholder,
});

function EvidenceDetailPlaceholder() {
    const { cid, eid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[
          { label: "Cases", to: "/cases" },
          { label: cid, to: `/cases/${cid}` },
          { label: "Evidence", to: `/cases/${cid}/evidence` },
          { label: eid },
        ]}
        caseId={cid}
        icon={ScanSearch}
        title="Evidence detail"
        description="Identification (ranked vendor matches with reasons), scan pipeline progress, the Tier B inferred-layout panel and device log events for this image."
        owner="WEB (Wave 2)"
      />
    );
}
