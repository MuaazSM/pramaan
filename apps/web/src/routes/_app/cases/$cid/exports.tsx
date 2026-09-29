/** /cases/$cid/exports — Exports. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { PackageCheck } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/exports")({
  component: ExportsPlaceholder,
});

function ExportsPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Exports" }]}
        caseId={cid}
        icon={PackageCheck}
        title="Exports"
        description="Range picker seeded from a review selection, the export list, and a verify drop zone with clear result states for a signed export bundle."
        owner="WEB (Wave 4)"
      />
    );
}
