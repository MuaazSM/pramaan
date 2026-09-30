import { useCallback, useEffect, useState } from "react";
import type { components } from "@/api/schema.gen";

type ExportRecord = components["schemas"]["ExportRecord"];

/**
 * Exports created in this browser session for one case.
 *
 * The OpenAPI contract has no `GET /api/cases/{cid}/exports` list endpoint (only POST), so the
 * server cannot tell us about earlier exports. This keeps a per-case list in `sessionStorage`
 * (survives in-tab navigation, cleared when the tab closes) seeded empty and appended to from
 * each successful POST. It is NOT an export history and the UI never calls it one.
 * Storage access is wrapped in try/catch — it can throw or come back empty in private windows.
 */
function storageKey(caseId: string): string {
  return `pramaan.exports.session.${caseId}`;
}

function load(caseId: string): ExportRecord[] {
  try {
    const raw = sessionStorage.getItem(storageKey(caseId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ExportRecord[]) : [];
  } catch {
    return [];
  }
}

export function useSessionExports(caseId: string): { exports: ExportRecord[]; add: (record: ExportRecord) => void } {
  const [exports, setExports] = useState<ExportRecord[]>(() => load(caseId));

  useEffect(() => {
    setExports(load(caseId));
  }, [caseId]);

  const add = useCallback(
    (record: ExportRecord) => {
      setExports((prev) => {
        // Export ids are content-derived, so re-exporting the same range yields the same id:
        // replace rather than list it twice.
        const next = [record, ...prev.filter((r) => r.id !== record.id)];
        try {
          sessionStorage.setItem(storageKey(caseId), JSON.stringify(next));
        } catch {
          // storage unavailable — the in-memory list still works for this page view
        }
        return next;
      });
    },
    [caseId],
  );

  return { exports, add };
}
