/** /cases/$cid/review — Review workspace (hero screen). Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { PlaySquare } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/review")({
  component: ReviewPlaceholder,
});

function ReviewPlaceholder() {
    const { cid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[{ label: "Cases", to: "/cases" }, { label: cid, to: `/cases/${cid}` }, { label: "Review" }]}
        caseId={cid}
        icon={PlaySquare}
        title="Review workspace"
        description="Multi-camera synced timeline, 1/4/9 video grid, frame inspector with the clock stack and Prove it. The most-built screen of Wave 3 — Frame.io and DaVinci Resolve are the references."
        owner="WEB (Wave 3)"
      />
    );
}
