/** /cases/$cid/recordings — Recordings table. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { Video } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/recordings")({
  component: RecordingsPlaceholder,
});

function RecordingsPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Recordings" }]}
        caseId={cid}
        icon={Video}
        title="Recordings"
        description="Virtualised table: channel, source (index / carved / inferred), deleted badge, device and normalised time, duration, size. Opens directly into the review workspace."
        owner="WEB (Wave 2)"
      />
    );
}
