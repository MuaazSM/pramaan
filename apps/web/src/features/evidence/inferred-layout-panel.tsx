import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Ruler, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { useToast } from "@/components/ui/use-toast";
import { TierBadge } from "@/components/signature/tier-badge";
import { api } from "@/api/client";

const FIELD_COLOR: Record<string, string> = {
  magic: "var(--ch-1)",
  channel: "var(--ch-2)",
  timestamp: "var(--ch-3)",
  length: "var(--ch-4)",
  sequence: "var(--ch-5)",
  flags: "var(--ch-6)",
  unknown: "var(--ink-500)",
};

/**
 * Tier B inferred-layout panel: field table + byte ruler + Confirm layout, for images with no
 * known vendor index (docs/04-FRONTEND.md §5). Renders nothing (not even a skeleton) when the
 * evidence has no inferred layout at all — that's the common case (Tier A images are parsed from
 * a known index, not inferred).
 */
export function InferredLayoutPanel({ eid }: { eid: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const query = useQuery({
    queryKey: ["inferred-layout", eid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/evidence/{eid}/inferred-layout", { params: { path: { eid } } });
      if (error) {
        if (response.status === 404) return null;
        throw new Error("failed to load inferred layout");
      }
      return data ?? null;
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async (lid: string) => {
      const { data, error } = await api.POST("/api/inferred-layouts/{lid}/confirm", { params: { path: { lid } } });
      if (error || !data) throw new Error("confirm failed");
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["inferred-layout", eid], data);
      toast({ title: "Layout confirmed", description: "The inferred structure is now part of this image's record." });
    },
    onError: () => {
      toast({ title: "Could not confirm layout", description: "Check your role — reviewers cannot confirm layouts.", variant: "danger" });
    },
  });

  if (query.isLoading) return <Skeleton className="h-40 w-full" />;
  const layout = query.data;
  if (!layout) return null;

  return (
    <section className="rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--inferred)_35%,transparent)] bg-[color-mix(in_oklab,var(--inferred)_6%,var(--panel))] p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Ruler size={14} strokeWidth={1.75} className="text-inferred" />
          <h2 className="text-section text-text">Inferred layout</h2>
          {/* F6: the signature TierBadge component ("B · inferred", BRAND.md §8) plus a plain
              caption, instead of a hand-rolled pill duplicating the same "Tier B" fact twice. */}
          <TierBadge tier="B" />
          <span className="text-caption text-text-3">structure inferred, not vendor-confirmed</span>
        </div>
        {layout.confirmed_by ? (
          <span className="flex items-center gap-1 text-label text-ok">
            <Check size={13} strokeWidth={2} /> Confirmed by {layout.confirmed_by}
          </span>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => confirmMutation.mutate(layout.id)} disabled={confirmMutation.isPending}>
            Confirm layout
          </Button>
        )}
      </div>

      {/* F6: each fact self-labelled and spaced, not dot-joined. */}
      <p className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-2">
        <span>Header length <span className="font-data text-text">{layout.header_len}</span> bytes</span>
        <span>Codec <span className="font-data text-text">{layout.codec}</span></span>
        <span>Magic <span className="font-data text-text">{layout.magic ?? "not recognised"}</span></span>
      </p>

      {/* Byte ruler: header_len bytes, each field positioned/sized proportionally. */}
      <div className="mb-3">
        <div className="relative h-6 w-full overflow-hidden rounded-[var(--radius-control)] border border-line-strong bg-control">
          {layout.fields.map((f) => (
            <Tooltip key={f.name}>
              <TooltipTrigger asChild>
                <div
                  className="absolute top-0 h-full border-r border-[var(--ink-950)]"
                  style={{
                    left: `${(f.offset / layout.header_len) * 100}%`,
                    width: `${(f.width / layout.header_len) * 100}%`,
                    backgroundColor: FIELD_COLOR[f.name] ?? "var(--ink-500)",
                    opacity: 0.55 + f.confidence * 0.4,
                  }}
                />
              </TooltipTrigger>
              <TooltipContent>
                {f.name}, offset {f.offset}, {f.width}B, {Math.round(f.confidence * 100)}% confidence
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
        <div className="mt-1 flex justify-between font-data text-caption text-text-3">
          <span>0x00</span>
          <span>0x{layout.header_len.toString(16).padStart(2, "0")}</span>
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Field</TableHead>
            <TableHead>Offset</TableHead>
            <TableHead>Width</TableHead>
            <TableHead>Endian</TableHead>
            <TableHead>Unit</TableHead>
            <TableHead>Confidence</TableHead>
            <TableHead>Support</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {layout.fields.map((f) => (
            <TableRow key={f.name}>
              <TableCell>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-sm" style={{ backgroundColor: FIELD_COLOR[f.name] ?? "var(--ink-500)" }} aria-hidden />
                  {f.name}
                </span>
              </TableCell>
              <TableCell className="font-data tabular-nums">{f.offset}</TableCell>
              <TableCell className="font-data tabular-nums">{f.width}B</TableCell>
              <TableCell className="font-data">{f.endian}</TableCell>
              <TableCell className="font-data">{f.unit}</TableCell>
              <TableCell className="font-data tabular-nums">{Math.round(f.confidence * 100)}%</TableCell>
              <TableCell className="font-data tabular-nums text-text-2">{f.support.toLocaleString()}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}
