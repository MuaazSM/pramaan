/**
 * /cases/$cid/recordings — Recordings.
 * Primary action: Open in review. Virtualised table (TanStack Virtual): channel, source
 * (index/carved/inferred), status (deleted/recovered), device + normalised time, duration, size.
 * Reference products studied: Stripe Dashboard (dense filterable data table), Linear (row
 * density, keyboard-friendly tables).
 */
import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Link } from "@tanstack/react-router";
import { Video, PlaySquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TableHeader, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { formatBytes, formatDuration, formatTimecodeUs } from "@/lib/format";
import { useUiStore } from "@/store/ui";
import { cn } from "@/lib/utils";
import type { components } from "@/api/schema.gen";

type Recording = components["schemas"]["Recording"];
type ClockModel = components["schemas"]["ClockModel"];
type SourceFilter = "all" | Recording["source"];
type StatusFilter = "all" | "active" | "recovered";

const SOURCE_LABEL: Record<Recording["source"], string> = { index: "index", carved: "carved", inferred: "inferred" };

/** Applies a channel's clock model (piecewise offset) to a device-clock microsecond value. */
function normalise(deviceUs: number, clock: ClockModel | undefined): number {
  if (!clock) return deviceUs;
  const seg = clock.segments.find(
    (s) => (s.from_device_us == null || deviceUs >= s.from_device_us) && (s.to_device_us == null || deviceUs < s.to_device_us),
  );
  return deviceUs + (seg?.offset_us ?? 0);
}

export function RecordingsScreen({ cid }: { cid: string }) {
  const density = useUiStore((s) => s.density);
  const rowHeight = density === "compact" ? 28 : 36;
  const parentRef = useRef<HTMLDivElement>(null);

  const [channel, setChannel] = useState<number | "all">("all");
  const [source, setSource] = useState<SourceFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [fromLocal, setFromLocal] = useState("");
  const [toLocal, setToLocal] = useState("");

  const recordingsQuery = useQuery({
    queryKey: ["recordings", cid],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/recordings", { params: { path: { cid } } });
      if (error) throw errorFromResponse(response, "recordings could not be loaded");
      return data ?? [];
    },
  });
  const clocksQuery = useQuery({
    queryKey: ["clock-models", cid],
    queryFn: async () => (await api.GET("/api/cases/{cid}/clock-models", { params: { path: { cid } } })).data ?? [],
  });

  const clockByChannel = useMemo(() => {
    const map = new Map<number, ClockModel>();
    for (const c of clocksQuery.data ?? []) if (c.channel != null) map.set(c.channel, c);
    return map;
  }, [clocksQuery.data]);

  const channels = useMemo(() => {
    const set = new Set<number>();
    for (const r of recordingsQuery.data ?? []) set.add(r.channel);
    return [...set].sort((a, b) => a - b);
  }, [recordingsQuery.data]);

  const fromUs = fromLocal ? Date.parse(fromLocal) * 1000 : null;
  const toUs = toLocal ? Date.parse(toLocal) * 1000 : null;

  const filtered = useMemo(() => {
    return (recordingsQuery.data ?? []).filter((r) => {
      if (channel !== "all" && r.channel !== channel) return false;
      if (source !== "all" && r.source !== source) return false;
      if (status === "active" && r.deleted) return false;
      if (status === "recovered" && !r.deleted) return false;
      if (fromUs != null && (r.end_ts_us ?? 0) < fromUs) return false;
      if (toUs != null && (r.start_ts_us ?? 0) > toUs) return false;
      return true;
    });
  }, [recordingsQuery.data, channel, source, status, fromUs, toUs]);

  const rowVirtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });
  const virtualItems = rowVirtualizer.getVirtualItems();
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom = virtualItems.length > 0 ? rowVirtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end : 0;

  const isLoading = recordingsQuery.isLoading;
  const total = recordingsQuery.data?.length ?? 0;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">Recordings</h1>
          <p className="text-[13px] text-text-2">
            {isLoading ? "Loading…" : `${filtered.length.toLocaleString()} of ${total.toLocaleString()} recordings`}
          </p>
        </div>
      </div>

      {/* Filters as chips */}
      <div className="flex flex-wrap items-center gap-2">
        <ChipGroup label="Channel">
          <Chip active={channel === "all"} onClick={() => setChannel("all")}>All</Chip>
          {channels.map((ch) => (
            <Chip key={ch} active={channel === ch} onClick={() => setChannel(ch)}>
              <span className="mr-1 inline-block size-1.5 rounded-full" style={{ backgroundColor: `var(--ch-${((ch - 1) % 8) + 1})` }} aria-hidden />
              CH{ch}
            </Chip>
          ))}
        </ChipGroup>
        <ChipGroup label="Source">
          {(["all", "index", "carved", "inferred"] as SourceFilter[]).map((s) => (
            <Chip key={s} active={source === s} onClick={() => setSource(s)}>
              {s === "all" ? "All" : SOURCE_LABEL[s]}
            </Chip>
          ))}
        </ChipGroup>
        <ChipGroup label="Status">
          <Chip active={status === "all"} onClick={() => setStatus("all")}>All</Chip>
          <Chip active={status === "active"} onClick={() => setStatus("active")}>Active</Chip>
          <Chip active={status === "recovered"} onClick={() => setStatus("recovered")}>Recovered</Chip>
        </ChipGroup>
        <div className="flex items-center gap-1.5 text-xs text-text-2">
          <span className="text-text-3">Device time</span>
          <input
            type="datetime-local"
            value={fromLocal}
            onChange={(e) => setFromLocal(e.target.value)}
            aria-label="From device time"
            className="focus-ring h-7 rounded-[var(--radius-control)] border border-line-strong bg-control px-2 font-mono text-[11px] text-text"
          />
          <span className="text-text-3">to</span>
          <input
            type="datetime-local"
            value={toLocal}
            onChange={(e) => setToLocal(e.target.value)}
            aria-label="To device time"
            className="focus-ring h-7 rounded-[var(--radius-control)] border border-line-strong bg-control px-2 font-mono text-[11px] text-text"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : recordingsQuery.isError ? (
        <QueryErrorState error={recordingsQuery.error} subject="recordings" onRetry={() => void recordingsQuery.refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyRecordings hasAny={total > 0} />
      ) : (
        <div ref={parentRef} className="overflow-auto rounded-[var(--radius-card)] border border-line" style={{ height: "min(64vh, 640px)" }}>
          <table className="w-full caption-bottom text-[13px]">
            <TableHeader>
              <TableRow>
                <TableHead>Channel</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Device time</TableHead>
                <TableHead>Normalised (IST)</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Size</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <tbody>
              {paddingTop > 0 && (
                <tr aria-hidden style={{ height: paddingTop }}>
                  <td colSpan={8} />
                </tr>
              )}
              {virtualItems.map((vi) => {
                const r = filtered[vi.index];
                const clock = clockByChannel.get(r.channel);
                const durationS = ((r.end_ts_us ?? 0) - (r.start_ts_us ?? 0)) / 1_000_000;
                const bytes = r.byte_ranges.reduce((s, b) => s + b.length, 0);
                return (
                  <TableRow key={r.id} data-index={vi.index} tabIndex={0} className="focus-ring">
                    <TableCell>
                      <span className="flex items-center gap-1.5">
                        <span className="size-2 rounded-full" style={{ backgroundColor: `var(--ch-${((r.channel - 1) % 8) + 1})` }} aria-hidden />
                        CH{r.channel}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={r.source === "index" ? "neutral" : r.source === "carved" ? "recovered" : "ai"}>{SOURCE_LABEL[r.source]}</Badge>
                    </TableCell>
                    <TableCell>
                      {r.deleted ? <Badge variant="recovered">recovered</Badge> : <Badge variant="ok">active</Badge>}
                    </TableCell>
                    <TableCell className="font-mono tabular-nums text-text-2">
                      {r.start_ts_us != null ? formatTimecodeUs(r.start_ts_us) : "—"}
                    </TableCell>
                    <TableCell className="font-mono tabular-nums">
                      {r.start_ts_us != null ? formatTimecodeUs(normalise(r.start_ts_us, clock)) : "—"}
                    </TableCell>
                    <TableCell className="tabular-nums text-text-2">{formatDuration(durationS)}</TableCell>
                    <TableCell className="tabular-nums text-text-2">{formatBytes(bytes)}</TableCell>
                    <TableCell>
                      <Button asChild size="sm" variant="ghost">
                        <Link to="/cases/$cid/review" params={{ cid }}>
                          <PlaySquare size={13} strokeWidth={1.75} />
                          Open in review
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {paddingBottom > 0 && (
                <tr aria-hidden style={{ height: paddingBottom }}>
                  <td colSpan={8} />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ChipGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-line-strong bg-card py-0.5 pl-2.5 pr-1">
      <span className="text-[10px] uppercase tracking-wide text-text-3">{label}</span>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "focus-ring rounded-full border px-2 py-1 text-[11px] font-medium transition-colors duration-[var(--dur-fast)]",
        active
          ? "border-[color-mix(in_oklab,var(--brand-500)_45%,transparent)] bg-[var(--selected)] text-accent-text"
          : "border-transparent text-text-2 hover:text-text",
      )}
    >
      {children}
    </button>
  );
}

function EmptyRecordings({ hasAny }: { hasAny: boolean }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-panel)] border border-dashed border-line-strong py-16 text-center">
      <Video size={28} strokeWidth={1.5} className="text-text-3" />
      <p className="text-[13px] text-text-2">{hasAny ? "No recordings match these filters." : "No recordings indexed yet — run a scan first."}</p>
    </div>
  );
}
