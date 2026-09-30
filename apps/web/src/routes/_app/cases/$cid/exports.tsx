/**
 * /cases/$cid/exports — Exports. See src/features/exports/exports-screen.tsx for the screen brief.
 * Primary action: Create signed export (+ a contained secondary "Verify export" drop zone).
 * Reference products studied: Stripe Dashboard (create form beside a results list, calm hashed
 * identifiers, explicit success/failure states).
 * Optional search params (`recording_id`, `channel`, `from_norm_us`, `to_norm_us`) prefill the
 * range form so a review selection can link here; the sending side is not wired yet.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useCaseLabel } from "@/api/labels";
import { ScreenShell } from "@/components/shell/screen-shell";
import { ExportsScreen } from "@/features/exports/exports-screen";

export interface ExportsSearch {
  recording_id?: string;
  channel?: number;
  from_norm_us?: number;
  to_norm_us?: number;
}

function asInt(v: unknown): number | undefined {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isInteger(n) ? n : undefined;
}

/** Manual (zod-free) narrowing of the raw search object; invalid values are dropped, not thrown. */
export function parseExportsSearch(search: Record<string, unknown>): ExportsSearch {
  const out: ExportsSearch = {};
  const rec = search.recording_id;
  if ((typeof rec === "string" && rec !== "") || typeof rec === "number") out.recording_id = String(rec);
  const channel = asInt(search.channel);
  if (channel !== undefined) out.channel = channel;
  const from = asInt(search.from_norm_us);
  if (from !== undefined) out.from_norm_us = from;
  const to = asInt(search.to_norm_us);
  if (to !== undefined) out.to_norm_us = to;
  return out;
}

export const Route = createFileRoute("/_app/cases/$cid/exports")({
  validateSearch: parseExportsSearch,
  component: ExportsRoute,
});

function ExportsRoute() {
  const { cid } = Route.useParams();
  const caseLabel = useCaseLabel(cid);
  return (
    <ScreenShell segments={[{ label: "Cases", to: "/cases" }, { label: caseLabel, to: `/cases/${cid}` }, { label: "Exports" }]} caseId={cid} showCustodySeal>
      <ExportsScreen caseId={cid} />
    </ScreenShell>
  );
}
