import { useState } from "react";
import { ChevronDown, FileBadge, FileText, ListTree } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { formatTimecode } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ReportRecord } from "../lib/manifest";
import { ManifestView } from "./manifest-view";

/**
 * One generated report. PDF and certificate are plain same-origin links (cookie session is sent
 * by the browser, no fetch+blob needed); the manifest is fetched on demand and shown as rows.
 */
export function ReportCard({ report, latest }: { report: ReportRecord; latest: boolean }) {
  const [open, setOpen] = useState(false);
  const panelId = `manifest-${report.id}`;

  return (
    <li className="rounded-[var(--radius-panel)] border border-line bg-panel p-4" data-testid="report-row">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
            <FileText size={16} strokeWidth={1.75} className="text-text-2" />
          </span>
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-section text-text">
              <span className="font-data tabular-nums">{report.id}</span>
              {latest && <Badge variant="brand">latest</Badge>}
            </h2>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-text-2">
              <span>{report.examiner}</span>
              <span className="font-data tabular-nums">{formatTimecode(report.created_utc)}</span>
            </p>
          </div>
        </div>
        <IntegrityChip state="verified" algo="sha256" hash={report.report_sha256} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button asChild size="sm" variant="secondary">
          <a href={`/api/reports/${encodeURIComponent(report.id)}/pdf`} target="_blank" rel="noopener noreferrer">
            <FileText size={14} strokeWidth={1.75} />
            PDF
          </a>
        </Button>
        <Button asChild size="sm" variant="secondary">
          <a href={`/api/reports/${encodeURIComponent(report.id)}/certificate.pdf`} target="_blank" rel="noopener noreferrer">
            <FileBadge size={14} strokeWidth={1.75} />
            BSA §63 certificate
          </a>
        </Button>
        <Button
          size="sm"
          variant="secondary"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
        >
          <ListTree size={14} strokeWidth={1.75} />
          Manifest
          <ChevronDown size={12} strokeWidth={1.75} className={cn("transition-transform", open && "rotate-180")} />
        </Button>
      </div>

      {open && (
        <div id={panelId} className="mt-3">
          <ManifestView report={report} />
        </div>
      )}
    </li>
  );
}
