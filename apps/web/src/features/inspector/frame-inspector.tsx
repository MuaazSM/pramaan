/**
 * Frame inspector — exported for the review workspace to mount (docs/04-FRONTEND.md §5.1:
 * "Inspector: frame thumbnail, clock stack, lineage breadcrumb, integrity chip for the payload
 * hash, buttons: Prove it, Add to report, Export range"). Also used standalone as the context
 * panel on the prove-it screen (features/prove/prove-view.tsx) — the same component, same props,
 * so "the panel review mounts" and "the panel prove-it shows" are never two implementations that
 * can drift apart.
 *
 * Mount: `import { FrameInspector } from "@/features/inspector/frame-inspector"` and render
 * `<FrameInspector caseId={cid} frameId={frameId} />` — see docs/progress/F3b.md "How to mount".
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Binary, FileStack, FileText, PackageOpen, ScanEye, SearchX } from "lucide-react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ClockStack } from "@/components/signature/clock-stack";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { LineageBreadcrumb, type LineageSegment } from "@/components/signature/lineage-breadcrumb";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { errorFromResponse } from "@/lib/api-error";
import { formatBytes, formatTimecode, shortHash } from "@/lib/format";
import { resolveClockStack } from "./lib/clock-readings";
import { useFrameHex } from "@/features/prove/lib/use-frame-hex";

const SOURCE_BADGE: Record<string, "neutral" | "recovered" | "ai"> = { index: "neutral", carved: "recovered", inferred: "ai" };

export function FrameInspector({ caseId, frameId }: { caseId: string; frameId: string }) {
  const frameQuery = useQuery({
    queryKey: ["frame", frameId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/frames/{fid}", { params: { path: { fid: frameId } } });
      if (error) {
        // A confirmed 404 is a distinct, well-understood state ("this frame id doesn't exist") —
        // not thrown, so it renders its own precise copy below instead of QueryErrorState's more
        // hedged "couldn't load" message, which is reserved for genuine failures (401/403/5xx/network).
        if (response.status === 404) return null;
        throw errorFromResponse(response, "this frame could not be loaded");
      }
      return data ?? null;
    },
  });
  const frame = frameQuery.data;

  const evidenceQuery = useQuery({
    queryKey: ["evidence", frame?.image_id],
    queryFn: async () => (await api.GET("/api/evidence/{eid}", { params: { path: { eid: frame!.image_id } } })).data ?? null,
    enabled: Boolean(frame?.image_id),
  });

  const recordingQuery = useQuery({
    queryKey: ["recording", frame?.recording_id],
    queryFn: async () => (await api.GET("/api/recordings/{rid}", { params: { path: { rid: frame!.recording_id! } } })).data ?? null,
    enabled: Boolean(frame?.recording_id),
  });

  const clockModelsQuery = useQuery({
    queryKey: ["clock-models", caseId],
    queryFn: async () => (await api.GET("/api/cases/{cid}/clock-models", { params: { path: { cid: caseId } } })).data ?? [],
  });

  const hexQuery = useFrameHex(frame?.frame_id);

  if (frameQuery.isLoading) return <InspectorSkeleton />;

  if (frameQuery.isError) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <QueryErrorState error={frameQuery.error} subject="this frame" onRetry={() => void frameQuery.refetch()} />
      </div>
    );
  }

  if (!frame) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <SearchX size={20} strokeWidth={1.5} className="text-text-3" />
        <div>
          <p className="text-base font-medium text-text">Frame not found</p>
          <p className="mt-1 text-sm text-text-2">frame_id <span className="font-data">{frameId}</span> does not exist in this case.</p>
        </div>
      </div>
    );
  }

  const clock = (clockModelsQuery.data ?? []).find((c) => c.channel === frame.channel);
  const { readings, chosenKey } = resolveClockStack(frame, clock);

  const segments: LineageSegment[] = [
    { label: "Evidence", to: `/cases/${caseId}/evidence/${frame.image_id}` },
    ...(frame.recording_id ? [{ label: "Recording", to: `/cases/${caseId}/recordings` }] : []),
    { label: `Frame ${shortHash(frame.frame_id, 6, 4)}` },
  ];

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-3">
      {/* Thumbnail */}
      <div className="relative aspect-video w-full overflow-hidden rounded-[var(--radius-control)] border border-line-strong bg-[color-mix(in_oklab,black_70%,var(--ink-900))]">
        <img
          src={`/api/frames/${frame.frame_id}/thumb`}
          alt={`Frame ${frame.frame_id} thumbnail`}
          className="h-full w-full object-cover"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
        {/* Fixed light text (`--ink-100`/`--ink-300`, not the theme-flipped `text-text` roles):
            this badge sits on the thumbnail's permanently-dark canvas (see the container's
            comment) in both themes, same convention as video-tile.tsx's "leader" badge — using
            theme-aware text here made these badges unreadable in light mode (caught in
            iteration 1's screenshots). */}
        <span className="absolute left-1.5 top-1.5 rounded bg-[rgba(7,8,11,0.72)] px-1.5 py-0.5 font-data text-caption text-[var(--ink-100)]">
          CH{frame.channel ?? "—"}
        </span>
        <span className="absolute right-1.5 top-1.5 rounded bg-[rgba(7,8,11,0.72)] px-1.5 py-0.5 font-data text-caption text-[var(--ink-300)]">
          {frame.frame_type}
        </span>
      </div>

      <LineageBreadcrumb segments={segments} />

      {/* Metadata */}
      <section>
        <SectionHeading icon={FileText} label="Frame" />
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <Field label="Frame ID" value={shortHash(frame.frame_id, 10, 6)} mono title={frame.frame_id} />
          <Field label="Codec" value={frame.codec.toUpperCase()} mono />
          <Field label="Type" value={frame.frame_type} mono />
          <Field label="Dimensions" value={frame.width && frame.height ? `${frame.width}×${frame.height}` : "—"} mono />
          <Field label="Payload" value={formatBytes(frame.payload_len)} mono />
          <Field label="Deleted" value={frame.deleted ? "yes — recovered" : "no"} />
        </dl>
        <div className="mt-2 flex items-center gap-1.5">
          <Badge variant={SOURCE_BADGE[frame.source]}>{frame.source}</Badge>
          {frame.deleted && <Badge variant="recovered">recovered</Badge>}
        </div>
      </section>

      {/* Four-clock stack */}
      <section>
        <SectionHeading icon={ScanEye} label="Clock stack" />
        <ClockStack readings={readings} chosenKey={chosenKey} />
      </section>

      {/* Integrity */}
      <section>
        <SectionHeading icon={Binary} label="Integrity" />
        {hexQuery.isLoading ? (
          <Skeleton className="h-7 w-full" />
        ) : hexQuery.data ? (
          <IntegrityChip
            state={hexQuery.data.matches ? "verified" : "mismatch"}
            hash={hexQuery.data.payload_sha256_stored}
          />
        ) : (
          <p className="text-caption text-text-3">Payload hash not available.</p>
        )}
      </section>

      {/* Provenance */}
      <section>
        <SectionHeading icon={PackageOpen} label="Provenance" />
        {evidenceQuery.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : evidenceQuery.data ? (
          <dl className="grid grid-cols-1 gap-1.5">
            <Field label="Evidence image" value={evidenceQuery.data.id} mono />
            <Field label="Image SHA-256" value={shortHash(evidenceQuery.data.sha256)} mono title={evidenceQuery.data.sha256} />
            <Field label="Acquired" value={formatTimecode(evidenceQuery.data.acquired_utc)} mono />
            <Field
              label="Header / payload offset"
              value={`${frame.header_offset ?? "—"} / ${frame.payload_offset}`}
              mono
            />
            {recordingQuery.data && (
              <Field label="Recording" value={`${recordingQuery.data.id} (${recordingQuery.data.source})`} mono />
            )}
          </dl>
        ) : (
          <p className="text-caption text-text-3">Evidence record unavailable.</p>
        )}
      </section>

      {/* Actions */}
      <section className="mt-auto flex flex-col gap-1.5 border-t border-line pt-3">
        <Button asChild size="sm">
          <Link to="/cases/$cid/frames/$fid/prove" params={{ cid: caseId, fid: frame.frame_id }}>
            <Binary size={13} strokeWidth={1.75} />
            Prove it
          </Link>
        </Button>
        <div className="flex gap-1.5">
          <Button asChild size="sm" variant="secondary" className="flex-1">
            <Link to="/cases/$cid/reports" params={{ cid: caseId }}>
              <FileText size={13} strokeWidth={1.75} />
              Add to report
            </Link>
          </Button>
          <Button asChild size="sm" variant="secondary" className="flex-1">
            <Link to="/cases/$cid/exports" params={{ cid: caseId }}>
              <FileStack size={13} strokeWidth={1.75} />
              Export range
            </Link>
          </Button>
        </div>
      </section>
    </div>
  );
}

function SectionHeading({ icon: Icon, label }: { icon: typeof Binary; label: string }) {
  return (
    <div className="mb-1.5 flex items-center gap-1.5">
      <Icon size={12} strokeWidth={1.75} className="text-text-3" />
      <h3 className="text-label text-text-3">{label}</h3>
    </div>
  );
}

function Field({ label, value, mono, title }: { label: string; value: string; mono?: boolean; title?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-label text-text-3">{label}</dt>
      <dd className={mono ? "truncate font-data text-sm text-text" : "truncate text-sm text-text"} title={title}>
        {value}
      </dd>
    </div>
  );
}

function InspectorSkeleton() {
  return (
    <div className="flex flex-1 flex-col gap-4 p-3">
      <Skeleton className="aspect-video w-full" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-20 w-full" />
    </div>
  );
}
