import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { api } from "@/api/client";
import { formatTimecodeUs } from "@/lib/format";

const KIND_VARIANT: Record<string, "neutral" | "warn" | "danger"> = {
  hdd_format: "danger",
  time_change: "warn",
  config_change: "warn",
};

/** Device log events for this image (docs/04-FRONTEND.md §5: "device log events table"). */
export function DeviceLogTable({ cid, eid }: { cid: string; eid: string }) {
  const [kind, setKind] = useState<string>("all");

  const query = useQuery({
    queryKey: ["log-events", cid, kind],
    queryFn: async () =>
      (await api.GET("/api/cases/{cid}/log-events", { params: { path: { cid }, query: kind === "all" ? {} : { kind } } })).data ?? [],
  });

  const events = (query.data ?? []).filter((e) => e.image_id === eid).sort((a, b) => a.ts_device_us - b.ts_device_us);

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-panel p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ScrollText size={14} strokeWidth={1.75} className="text-text-3" />
          <h2 className="text-[13px] font-medium text-text">Device log events</h2>
        </div>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All kinds</SelectItem>
            {["login", "logout", "playback", "export", "hdd_format", "time_change", "config_change", "power_on", "other"].map((k) => (
              <SelectItem key={k} value={k}>
                {k.replace(/_/g, " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {query.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : events.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-text-2">No device log events{kind !== "all" ? ` of kind "${kind}"` : ""} for this image.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Device time</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Channel</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Details</TableHead>
              <TableHead>Offset</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="font-mono tabular-nums">{formatTimecodeUs(e.ts_device_us)}</TableCell>
                <TableCell>
                  <Badge variant={KIND_VARIANT[e.kind] ?? "neutral"}>{e.kind.replace(/_/g, " ")}</Badge>
                </TableCell>
                <TableCell className="tabular-nums text-text-2">{e.channel ?? "—"}</TableCell>
                <TableCell className="text-text-2">{e.user ?? "—"}</TableCell>
                <TableCell className="max-w-xs truncate font-mono text-[11px] text-text-3">
                  {Object.keys(e.details).length ? Object.entries(e.details).map(([k, v]) => `${k}=${String(v)}`).join(" ") : "—"}
                </TableCell>
                <TableCell className="font-mono tabular-nums text-text-3">0x{e.offset.toString(16)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
