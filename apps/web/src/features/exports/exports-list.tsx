/**
 * Exports created this session (NOT a history — the API has no list endpoint for exports, see
 * lib/session-exports.ts). One row per `ExportRecord` returned by `POST /cases/{cid}/exports`.
 * Download is a plain same-origin link to `GET /exports/{xid}/file` (cookie auth), the raw MP4.
 */
import { Download, PackageOpen } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { formatOffsetLabel, formatTimecode, formatTimecodeUs } from "@/lib/format";
import type { components } from "@/api/schema.gen";

type ExportRecord = components["schemas"]["ExportRecord"];

export function ExportsList({ records }: { records: ExportRecord[] }) {
  if (records.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-[var(--radius-panel)] border border-dashed border-line-strong py-14 text-center">
        <PackageOpen size={28} strokeWidth={1.5} className="text-text-3" aria-hidden />
        <div>
          <p className="text-base font-medium text-text">No exports created this session yet</p>
          <p className="mt-1 max-w-md text-sm text-text-2">
            Create a signed export above and it will appear here with its manifest hash and a download link.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
      <table className="w-full caption-bottom text-base">
        <TableHeader>
          <TableRow>
            <TableHead>Export</TableHead>
            <TableHead>Scope</TableHead>
            <TableHead>Normalised range (IST)</TableHead>
            <TableHead>Manifest hash</TableHead>
            <TableHead>Created (IST)</TableHead>
            <TableHead>Examiner</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <tbody>
          {records.map((r) => (
            <TableRow key={r.id} data-testid="export-row">
              <TableCell className="font-data text-sm tabular-nums text-text" title={r.id}>
                {r.id}
              </TableCell>
              <TableCell>
                <span className="flex flex-wrap items-center gap-1.5">
                  {r.channel != null && (
                    <span className="flex items-center gap-1.5 font-data text-sm">
                      <span className="size-2 rounded-full" style={{ backgroundColor: `var(--ch-${(((r.channel || 1) - 1) % 8) + 1})` }} aria-hidden />
                      CH{r.channel}
                    </span>
                  )}
                  {r.recording_id ? (
                    <Badge variant="neutral" className="font-data">
                      {r.recording_id}
                    </Badge>
                  ) : (
                    <span className="text-caption text-text-3">channel range</span>
                  )}
                </span>
              </TableCell>
              <TableCell className="font-data text-sm tabular-nums">
                <RangeCell from={r.from_norm_us} to={r.to_norm_us} wholeRecording={r.recording_id != null} />
              </TableCell>
              <TableCell>
                <IntegrityChip state="verified" hash={r.manifest_sha256} />
              </TableCell>
              <TableCell className="font-data text-sm tabular-nums text-text-2">{formatTimecode(r.created_utc)}</TableCell>
              <TableCell className="text-text-2">{r.examiner}</TableCell>
              <TableCell>
                <Button asChild size="sm" variant="secondary">
                  <a href={`/api/exports/${encodeURIComponent(r.id)}/file`} download={`${r.id}.mp4`} aria-label={`Download ${r.id}`}>
                    <Download size={13} strokeWidth={1.75} aria-hidden />
                    Download
                  </a>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RangeCell({ from, to, wholeRecording }: { from: number | null; to: number | null; wholeRecording: boolean }) {
  if (from == null && to == null) {
    return <span className="text-text-3">{wholeRecording ? "whole recording" : "unbounded"}</span>;
  }
  return (
    <div className="flex flex-col">
      <span>{from != null ? formatTimecodeUs(from) : "start of channel"}</span>
      <span className="text-text-3">
        → {to != null ? formatTimecodeUs(to) : "end of channel"}
        {from != null && to != null && <span className="ml-1.5 text-text-2">({formatOffsetLabel(to - from)})</span>}
      </span>
    </div>
  );
}
