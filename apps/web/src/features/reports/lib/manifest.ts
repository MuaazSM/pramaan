/**
 * Defensive readers for a report manifest. The API types it as an arbitrary JSON object: stub mode
 * returns a tiny shape (`report_id, case_id, report_sha256, examiner, created_utc, limitations`),
 * real mode returns `packages/reporting`'s full manifest (case, examiner, evidence, vendor_matches,
 * methods, recordings_summary, deletion_findings, clock_observations, log_events,
 * accepted_ai_drafts, custody, anchors, limitations). Nothing here assumes a key exists.
 */
import type { components } from "@/api/schema.gen";

export type ReportManifest = { [key: string]: unknown };
export type ReportRecord = components["schemas"]["ReportRecord"];

type Obj = Record<string, unknown>;

export function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Array entries that are objects (drops anything malformed rather than throwing). */
export function objectList(v: unknown): Obj[] {
  return Array.isArray(v) ? v.filter(isObj) : [];
}

export interface EvidenceHashRow {
  id: string;
  label: string | null;
  sha256: string | null;
  md5: string | null;
}

export interface ManifestSummary {
  facts: { label: string; value: string; mono: boolean }[];
  evidence: EvidenceHashRow[];
  limitations: string[];
  /** Other top-level keys that hold lists/objects, as `key · N entries`, for a "Contents" strip. */
  contents: { key: string; count: number }[];
}

const SHOWN_KEYS = new Set(["report_id", "case_id", "report_sha256", "examiner", "created_utc", "case", "evidence", "limitations", "custody"]);

function personLabel(v: unknown): string | null {
  if (typeof v === "string") return v;
  if (isObj(v)) return str(v.display_name) ?? str(v.name) ?? str(v.username) ?? str(v.id);
  return null;
}

function caseLabel(m: ReportManifest): string | null {
  if (isObj(m.case)) {
    const number = str(m.case.case_number);
    const title = str(m.case.title);
    if (number && title) return `${number} · ${title}`;
    return number ?? title ?? str(m.case.id);
  }
  return str(m.case_id);
}

export function summarizeManifest(m: ReportManifest, record?: ReportRecord): ManifestSummary {
  const facts: ManifestSummary["facts"] = [];
  const push = (label: string, value: string | null, mono = false) => {
    if (value) facts.push({ label, value, mono });
  };
  push("Report SHA-256", str(m.report_sha256) ?? record?.report_sha256 ?? null, true);
  push("Report id", str(m.report_id) ?? record?.id ?? null, true);
  push("Case", caseLabel(m));
  push("Examiner", personLabel(m.examiner) ?? record?.examiner ?? null);
  push("Created (UTC)", str(m.created_utc) ?? record?.created_utc ?? null, true);
  if (isObj(m.custody)) push("Custody head hash", str(m.custody.head_hash) ?? str(m.custody.head), true);

  const evidence = objectList(m.evidence).map((e) => ({
    id: str(e.id) ?? "evidence",
    label: str(e.path)?.split("/").pop() ?? str(e.label),
    sha256: str(e.sha256),
    md5: str(e.md5),
  }));

  const limitations = Array.isArray(m.limitations) ? m.limitations.filter((x): x is string => typeof x === "string") : [];

  const contents: ManifestSummary["contents"] = [];
  for (const [key, value] of Object.entries(m)) {
    if (SHOWN_KEYS.has(key)) continue;
    if (Array.isArray(value)) contents.push({ key, count: value.length });
    else if (isObj(value)) {
      // `recordings_summary: { count, recordings }` style — prefer the declared count.
      contents.push({ key, count: num(value.count) ?? Object.keys(value).length });
    }
  }
  contents.sort((a, b) => a.key.localeCompare(b.key));

  return { facts, evidence, limitations, contents };
}
