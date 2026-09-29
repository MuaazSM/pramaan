/** /cases/$cid/reports — Reports. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/reports")({
  component: ReportsPlaceholder,
});

function ReportsPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Reports" }]}
        caseId={cid}
        icon={FileText}
        title="Reports"
        description="PDF and BSA §63 certificate preview, manifest hash, download — with an AI draft block (per-sentence evidence chips, Accept/Reject) once the LLM workstream is enabled."
        owner="WEB (Wave 4)"
      />
    );
}
