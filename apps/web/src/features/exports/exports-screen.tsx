/**
 * /cases/$cid/exports — Exports.
 * Primary action: Create signed export. Composes the create/range form (seeded from URL search
 * params so a review selection can deep-link here), a verify drop zone, and the list of exports
 * created this session.
 * Reference products studied: Stripe Dashboard (create-object form beside a results list, calm
 * hashed-identifier display, clear success/failure states).
 */
import { useSearch } from "@tanstack/react-router";
import { CreateExportForm, type ExportPrefill } from "./create-export-form";
import { ExportsList } from "./exports-list";
import { VerifyZone } from "./verify-zone";
import { useSessionExports } from "./lib/session-exports";

export function ExportsScreen({ caseId }: { caseId: string }) {
  const search = useSearch({ from: "/_app/cases/$cid/exports" });
  const { exports, add } = useSessionExports(caseId);
  const prefill: ExportPrefill = {
    recording_id: search.recording_id,
    channel: search.channel,
    from_norm_us: search.from_norm_us,
    to_norm_us: search.to_norm_us,
  };

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">Exports</h1>
        <p className="text-[13px] text-text-2">
          ONVIF-style signed export (not conformance-tested). Video is remuxed by stream copy with a signed manifest; the original is never re-encoded.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-[var(--radius-panel)] border border-line bg-card p-4" aria-label="Create export">
          <CreateExportForm key={JSON.stringify(prefill)} caseId={caseId} prefill={prefill} onCreated={add} />
        </section>
        <section className="rounded-[var(--radius-panel)] border border-line bg-card p-4" aria-label="Verify export">
          <VerifyZone />
        </section>
      </div>

      <section className="flex flex-col gap-2" aria-labelledby="session-exports-heading">
        <div className="flex items-baseline justify-between">
          <h2 id="session-exports-heading" className="text-[15px] font-semibold tracking-[-0.01em] text-text">
            Exports created this session
          </h2>
          <span className="text-[11px] text-text-3">Not a history — cleared when this browser tab closes.</span>
        </div>
        <ExportsList records={exports} />
      </section>
    </div>
  );
}
