/** /cases/$cid/frames/$fid/prove — "Prove it" hex view. Designed placeholder for this wave. */
import { createFileRoute } from "@tanstack/react-router";
import { Binary } from "lucide-react";
import { PlaceholderScreen } from "@/components/shell/placeholder-screen";

export const Route = createFileRoute("/_app/cases/$cid/frames/$fid/prove")({
  component: ProvePlaceholder,
});

function ProvePlaceholder() {
    const { cid, fid } = Route.useParams();
    return (
      <PlaceholderScreen
        segments={[
          { label: "Cases", to: "/cases" },
          { label: cid, to: `/cases/${cid}` },
          { label: "Review", to: `/cases/${cid}/review` },
          { label: `Frame ${fid}` },
        ]}
        caseId={cid}
        icon={Binary}
        title="Prove it"
        description="An ImHex-style hex grid — offset gutter, 16-byte rows, ASCII pane — with annotated vendor header fields, a decoding inspector, sector numbers, and a live SHA-256 recompute."
        owner="WEB (Wave 3)"
      />
    );
}
