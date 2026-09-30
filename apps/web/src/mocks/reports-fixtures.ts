/**
 * Reports screen (F4) fixtures. Deterministic: fixed timestamps and hashes, no Date.now() or
 * Math.random(). All data is synthetic (CLAUDE.md rule 7) — the manifest says so in its own
 * `limitations`. Shapes follow `ReportRecord` / the real `packages/reporting` manifest keys
 * (case, examiner, evidence, deletion_findings, recordings_summary, custody, limitations).
 */
import type { components } from "@/api/schema.gen";
import { DEMO_CASE, DELETIONS_BY_CASE, EVIDENCE_BY_CASE, RECORDINGS_BY_CASE } from "./fixtures";

export type ReportRecord = components["schemas"]["ReportRecord"];
export type DraftSentenceOut = components["schemas"]["DraftSentenceOut"];

/** The report already on file when the demo case is first opened. */
export const SEED_REPORT: ReportRecord = {
  id: "rpt_7c1e4a90b2d3",
  case_id: DEMO_CASE.id,
  created_utc: "2026-03-17T16:20:00Z",
  report_sha256: "7c1e4a90b2d35f68a1e9c04b7d2f8a3e6b5c9d1f0a4e7b28c3d6f9a1e5b8c204",
  examiner: "examiner",
  pdf_path: "/data/reports/rpt_7c1e4a90b2d3/report.pdf",
  certificate_path: "/data/reports/rpt_7c1e4a90b2d3/certificate.pdf",
  manifest_path: "/data/reports/rpt_7c1e4a90b2d3/manifest.json",
};

/**
 * What "Generate report" produces in mock mode. Like the real backend (report id is derived from
 * the report hash), generating again over unchanged data yields the same record, so the mock
 * handler creates this record once and returns it on repeat calls.
 */
export const GENERATED_REPORT: ReportRecord = {
  id: "rpt_e5b8c204a1f9",
  case_id: DEMO_CASE.id,
  created_utc: "2026-03-18T09:30:00Z",
  report_sha256: "e5b8c204a1f97d3062b4c8e1a5f09d7b3c6e2a8f1d4b7095e3c6a9d2f8b1c470",
  examiner: "examiner",
  pdf_path: "/data/reports/rpt_e5b8c204a1f9/report.pdf",
  certificate_path: "/data/reports/rpt_e5b8c204a1f9/certificate.pdf",
  manifest_path: "/data/reports/rpt_e5b8c204a1f9/manifest.json",
};

export const REPORT_BY_ID: Record<string, ReportRecord> = {
  [SEED_REPORT.id]: SEED_REPORT,
  [GENERATED_REPORT.id]: GENERATED_REPORT,
};

export function buildMockManifest(report: ReportRecord): Record<string, unknown> {
  return {
    report_id: report.id,
    report_sha256: report.report_sha256,
    created_utc: report.created_utc,
    case: {
      id: DEMO_CASE.id,
      case_number: DEMO_CASE.case_number,
      title: DEMO_CASE.title,
      fir_reference: DEMO_CASE.fir_reference,
      lab: DEMO_CASE.lab,
    },
    examiner: { username: report.examiner, display_name: "R. Deshmukh" },
    evidence: (EVIDENCE_BY_CASE[DEMO_CASE.id] ?? []).map((e) => ({
      id: e.id,
      path: e.path,
      format: e.format,
      size_bytes: e.size_bytes,
      sha256: e.sha256,
      md5: e.md5,
      acquired_utc: e.acquired_utc,
    })),
    deletion_findings: (DELETIONS_BY_CASE[DEMO_CASE.id] ?? []).map((d) => ({
      id: d.id,
      method: d.method,
      channel: d.channel,
      frames_recovered: d.frames_recovered,
      confidence: d.confidence,
      actor: d.actor,
      evidence_refs: d.evidence_refs,
    })),
    recordings_summary: { count: (RECORDINGS_BY_CASE[DEMO_CASE.id] ?? []).length },
    custody: { head_hash: "c94d1e07a3b58f2260d9e4b7a1c58e3f92b6d0a47e1f8c35b2a9d6e0f4c81a73", entries: 11 },
    anchors: [],
    accepted_ai_drafts: [],
    limitations: [
      "Synthetic corpus: this demo case is fabricated fixture data modelled on published layouts, not a real vendor disk. No compatibility with real vendor disks is claimed.",
      "Deletion verdicts are inferences from index gaps, device logs and carved frames; each cites its evidence in the findings view.",
    ],
  };
}

/**
 * Draft sentences the mocked `assistant/draft` returns. They cite the ids `buildReportFacts`
 * (features/reports/lib/build-facts.ts) assigns over `buildMockManifest`: fact_1 is the deletion
 * finding, fact_2/fact_3 the two evidence images. Every number in each sentence appears in its
 * cited fact's own text (mirrors packages/llm/pramaan_llm/validator.py; asserted in
 * features/reports/lib/build-facts.test.ts). Only reachable when a build has `llm_enabled: true`.
 */
export const MOCK_DRAFT_SENTENCES: DraftSentenceOut[] = [
  { text: "One deletion event of type format was recorded on channel 3, with 214 frames recovered.", evidence_ids: ["fact_1"] },
  { text: "The deletion finding carries a stated confidence of 0.91.", evidence_ids: ["fact_1"] },
  { text: "Evidence ev_hiksim01 is registered with a recorded SHA-256 digest.", evidence_ids: ["fact_2"] },
];
