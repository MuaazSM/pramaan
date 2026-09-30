import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/api/client";
import { summarizeManifest, type ReportManifest, type ReportRecord } from "../lib/manifest";

/** Shared query so the manifest card and the AI draft section hit the network once per report. */
export function useReportManifest(reportId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["report-manifest", reportId],
    enabled: enabled && Boolean(reportId),
    queryFn: async (): Promise<ReportManifest> => {
      const { data, error } = await api.GET("/api/reports/{rid}/manifest", { params: { path: { rid: reportId! } } });
      if (error || !data) throw new Error("manifest unavailable");
      return data;
    },
  });
}

/**
 * Key rows + hash list, not a JSON dump. The manifest is freeform, so every section only renders
 * when the manifest actually has that data (see lib/manifest.ts).
 */
export function ManifestView({ report }: { report: ReportRecord }) {
  const query = useReportManifest(report.id);

  if (query.isLoading) {
    return <Skeleton className="h-40 w-full" />;
  }
  if (query.isError || !query.data) {
    return (
      <div role="alert" className="flex items-center gap-2 rounded-[var(--radius-card)] border border-line bg-card p-3 text-sm text-text-2">
        <AlertTriangle size={14} strokeWidth={1.75} className="text-danger" />
        Couldn't load this report's manifest.
      </div>
    );
  }

  const summary = summarizeManifest(query.data, report);

  return (
    <div className="flex flex-col gap-4 rounded-[var(--radius-card)] border border-line bg-card p-4" data-testid="manifest-view">
      <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-1.5 text-sm">
        {summary.facts.map((f) => (
          <div key={f.label} className="col-span-2 grid grid-cols-subgrid items-baseline">
            <dt className="text-text-3">{f.label}</dt>
            <dd className={f.mono ? "break-all font-data tabular-nums text-text" : "text-text"}>{f.value}</dd>
          </div>
        ))}
      </dl>

      {summary.evidence.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-label text-text-3">Evidence hashes</h4>
          <ul className="flex flex-col divide-y divide-line rounded-[var(--radius-control)] border border-line">
            {summary.evidence.map((e) => (
              <li key={e.id} className="flex flex-col gap-0.5 px-3 py-2 text-sm">
                <span className="flex flex-wrap items-baseline gap-x-1.5 text-text">
                  <span className="font-data">{e.id}</span>
                  {e.label && <span className="text-text-3">{e.label}</span>}
                </span>
                {e.sha256 && (
                  <span className="break-all font-data text-caption tabular-nums text-text-2">
                    <span className="text-text-3">sha256 </span>
                    {e.sha256}
                  </span>
                )}
                {e.md5 && (
                  <span className="break-all font-data text-caption tabular-nums text-text-2">
                    <span className="text-text-3">md5 </span>
                    {e.md5}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {summary.contents.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-label text-text-3">Also in the manifest</h4>
          <ul className="flex flex-wrap gap-1.5">
            {summary.contents.map((c) => (
              <li
                key={c.key}
                className="rounded-full border border-line-strong bg-control px-2 py-0.5 font-data text-caption tabular-nums text-text-2"
              >
                {c.key} ({c.count})
              </li>
            ))}
          </ul>
        </section>
      )}

      {summary.limitations.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-label text-text-3">Limitations</h4>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-sm text-text-2">
            {summary.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
