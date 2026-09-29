/** /cases/$cid/custody — Custody chain. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { Landmark } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/custody")({
  component: CustodyPlaceholder,
});

function CustodyPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Custody" }]}
        caseId={cid}
        icon={Landmark}
        title="Custody"
        description="Breadcrumb-style audit timeline, a chain verification result, and anchors (local / Fabric) with their Merkle roots. The case overview already surfaces the chain head in its footer strip."
        owner="WEB (Wave 2)"
      />
    );
}
