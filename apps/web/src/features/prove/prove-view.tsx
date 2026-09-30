/**
 * /cases/$cid/frames/$fid/prove — Prove it.
 * Primary action: Copy proof. An ImHex-style hex grid with annotated regions (vendor header,
 * start code, payload), a field decoder, disk sector numbers, and a live SHA-256 recompute (the
 * browser's own SubtleCrypto, independent of the server's claim) — this is the screen that proves
 * a frame's bytes are actually on the disk, not just described by the API. Composes
 * `FrameInspector` (features/inspector/) as context so the frame's clock stack, integrity and
 * provenance sit next to the byte-level proof.
 * Reference products studied: ImHex (hex grid, offset gutter, pattern highlighting, structure
 * inspector), Sentry (context-panel layout), Vercel/Geist (restrained mono type, deployment-log
 * tone for the recompute strip).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Binary, ChevronLeft, ChevronRight, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/use-toast";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { FrameInspector } from "@/features/inspector/frame-inspector";
import { FieldDecoder } from "./components/field-decoder";
import { HexGrid } from "./components/hex-grid";
import { ShaRecompute } from "./components/sha-recompute";
import { useFrameHex } from "./lib/use-frame-hex";
import { base64ToBytes, classifyAnnotations, type RawAnnotation } from "./lib/hex-annotate";

const BEFORE_STEP = 256;
const AFTER_STEP = 512;
const MAX_WINDOW = 8192;

export function ProveView({ caseId, frameId }: { caseId: string; frameId: string }) {
  const { toast } = useToast();
  const [before, setBefore] = useState(256);
  const [after, setAfter] = useState(512);
  const [hoveredName, setHoveredName] = useState<string | null>(null);

  const hexQuery = useFrameHex(frameId, before, after);
  const frameQuery = useQuery({
    queryKey: ["frame", frameId],
    queryFn: async () => (await api.GET("/api/frames/{fid}", { params: { path: { fid: frameId } } })).data ?? null,
  });

  const bytes = useMemo(() => (hexQuery.data ? base64ToBytes(hexQuery.data.bytes_b64) : null), [hexQuery.data]);
  const rawAnnotations = (hexQuery.data?.annotations ?? []) as unknown as RawAnnotation[];
  const annotations = useMemo(
    () => (hexQuery.data ? classifyAnnotations(rawAnnotations, hexQuery.data.offset) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hexQuery.data],
  );
  const payloadAnnotation = rawAnnotations.find((a) => a.name === "payload");

  async function copyProof() {
    if (!hexQuery.data) return;
    const proof = {
      frame_id: hexQuery.data.frame_id,
      window_offset: hexQuery.data.offset,
      before: hexQuery.data.before,
      after: hexQuery.data.after,
      payload_sha256_stored: hexQuery.data.payload_sha256_stored,
      payload_sha256_recomputed: hexQuery.data.payload_sha256_recomputed,
      matches: hexQuery.data.matches,
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(proof, null, 2));
      toast({
        title: "Proof copied",
        description: `${proof.frame_id.slice(0, 12)}… · sha256 ${proof.payload_sha256_stored.slice(0, 12)}…`,
      });
    } catch {
      toast({ title: "Couldn't copy", description: "Clipboard access was denied.", variant: "danger" });
    }
  }

  if (hexQuery.isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 p-6 lg:grid-cols-[1fr_320px]">
        <Skeleton className="h-[560px] w-full" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    );
  }

  if (hexQuery.isError || !hexQuery.data || !bytes) {
    return (
      <div className="flex h-full items-center justify-center p-10">
        <QueryErrorState
          error={hexQuery.error}
          subject="this frame's bytes"
          onRetry={hexQuery.isError ? () => void hexQuery.refetch() : undefined}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-page-title text-text">
            <Binary size={18} strokeWidth={1.75} className="text-text-3" />
            Prove it
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-label text-text-2">
            <span className="truncate font-data">{hexQuery.data.frame_id}</span>
            <span className="font-data">{bytes.length.toLocaleString()} bytes from offset 0x{hexQuery.data.offset.toString(16)}</span>
          </p>
        </div>
        <Button onClick={() => void copyProof()}>
          <Copy size={14} strokeWidth={1.75} />
          Copy proof
        </Button>
      </div>

      {payloadAnnotation && (
        <ShaRecompute
          frameId={hexQuery.data.frame_id}
          bytesB64={hexQuery.data.bytes_b64}
          payloadAnnotation={payloadAnnotation}
          storedHash={hexQuery.data.payload_sha256_stored}
        />
      )}

      {/*
        `items-stretch` (grid's default, made explicit) makes the hex-grid column match the
        right column's natural height instead of the hex grid sizing itself with a fixed
        viewport-relative height while the (taller) inspector column left a large empty gap below
        it — caught in iteration 1's screenshots. `min-h-0` on the left column + `flex-1 min-h-0`
        on HexGrid is what lets that stretched, definite height actually reach the scrollable
        virtualizer container instead of the flex column just overflowing it.
      */}
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-[1fr_320px]">
        <div className="flex min-h-0 min-w-0 flex-col gap-3">
          <div className="flex items-center gap-2">
            <WindowStepper
              label="Before"
              value={before}
              onDecrease={() => setBefore((v) => Math.max(0, v - BEFORE_STEP))}
              onIncrease={() => setBefore((v) => Math.min(MAX_WINDOW, v + BEFORE_STEP))}
            />
            <WindowStepper
              label="After"
              value={after}
              onDecrease={() => setAfter((v) => Math.max(0, v - AFTER_STEP))}
              onIncrease={() => setAfter((v) => Math.min(MAX_WINDOW, v + AFTER_STEP))}
            />
            {hexQuery.isFetching && <span className="text-caption text-text-3">{"Loading window…"}</span>}
          </div>
          <HexGrid
            bytes={bytes}
            windowOffset={hexQuery.data.offset}
            annotations={annotations}
            hoveredName={hoveredName}
            onHover={setHoveredName}
            className="min-h-0 flex-1"
          />
        </div>
        <div className="flex flex-col gap-4">
          <section className="rounded-[var(--radius-card)] border border-line bg-panel p-3">
            <h2 className="mb-2 text-label text-text-3">Fields</h2>
            <FieldDecoder
              bytes={bytes}
              annotations={annotations}
              codec={frameQuery.data?.codec ?? "h264"}
              hoveredName={hoveredName}
              onHover={setHoveredName}
            />
          </section>
          <section className="flex flex-1 flex-col rounded-[var(--radius-card)] border border-line bg-panel">
            <div className="border-b border-line px-3 py-2">
              <h2 className="text-label text-text-3">Frame context</h2>
            </div>
            <FrameInspector caseId={caseId} frameId={frameId} />
          </section>
        </div>
      </div>
    </div>
  );
}

function WindowStepper({
  label,
  value,
  onDecrease,
  onIncrease,
}: {
  label: string;
  value: number;
  onDecrease: () => void;
  onIncrease: () => void;
}) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-line-strong bg-card py-0.5 pl-2.5 pr-1 text-caption">
      <span className="text-text-3">{label}</span>
      <span className="font-data tabular-nums text-text">{value.toLocaleString()}B</span>
      <button type="button" onClick={onDecrease} aria-label={`Decrease ${label.toLowerCase()} window`} className="focus-ring rounded p-0.5 text-text-3 hover:bg-control hover:text-text">
        <ChevronLeft size={12} strokeWidth={1.75} />
      </button>
      <button type="button" onClick={onIncrease} aria-label={`Increase ${label.toLowerCase()} window`} className="focus-ring rounded p-0.5 text-text-3 hover:bg-control hover:text-text">
        <ChevronRight size={12} strokeWidth={1.75} />
      </button>
    </div>
  );
}
