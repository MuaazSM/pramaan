import { http, HttpResponse } from "msw";
import { DEMO_CASE } from "./fixtures";
import {
  GENERATED_REPORT,
  MOCK_DRAFT_SENTENCES,
  REPORT_BY_ID,
  SEED_REPORT,
  buildMockManifest,
  type DraftSentenceOut,
  type ReportRecord,
} from "./reports-fixtures";

/**
 * Reports (F4) MSW handlers: report list/create, the two PDF downloads, the manifest, and the
 * assistant draft. Own module per this task's ownership; spread into `handlers` in ./handlers.ts.
 * `GET /api/system/health` is served by the shared handler (HEALTH.llm_enabled is false), so in
 * mock mode the AI draft section is hidden and `assistant/draft` is never called by the app —
 * it exists so a build with llm_enabled flipped on has something honest to talk to.
 */

function currentUsername(): string | null {
  const cookie = typeof document !== "undefined" ? document.cookie : "";
  const match = /pramaan_session=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]) : null;
}

function unauthenticated() {
  return HttpResponse.json(
    { error: { code: "unauthenticated", message: "Sign in required.", details: {} } },
    { status: 401 },
  );
}

function notFound(what: string, id: string) {
  return HttpResponse.json(
    { error: { code: "not_found", message: `${what} ${id} not found.`, details: {} } },
    { status: 404 },
  );
}

/** A tiny but structurally valid one-page PDF (placeholder — not a real report). */
const PLACEHOLDER_PDF = new TextEncoder().encode(
  [
    "%PDF-1.4",
    "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj",
    "4 0 obj<</Length 66>>stream",
    "BT /F1 10 Tf 20 50 Td (Pramaan mock placeholder PDF) Tj ET",
    "endstream endobj",
    "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
    "trailer<</Root 1 0 R/Size 6>>",
    "%%EOF",
  ].join("\n"),
);

function pdfResponse() {
  return new HttpResponse(PLACEHOLDER_PDF, { headers: { "Content-Type": "application/pdf" } });
}

// Reports generated during this page session. Starts with the seeded report only.
let generated = false;

function currentReports(cid: string): ReportRecord[] {
  if (cid !== DEMO_CASE.id) return [];
  return generated ? [SEED_REPORT, GENERATED_REPORT] : [SEED_REPORT];
}

export const reportsHandlers = [
  http.get("/api/cases/:cid/reports", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    return HttpResponse.json(currentReports(params.cid as string));
  }),

  http.post("/api/cases/:cid/reports", async ({ params, request }) => {
    if (!currentUsername()) return unauthenticated();
    const cid = params.cid as string;
    if (cid !== DEMO_CASE.id) return notFound("case", cid);
    await request.json().catch(() => ({}));
    generated = true;
    return HttpResponse.json(GENERATED_REPORT, { status: 201 });
  }),

  http.get("/api/reports/:rid/pdf", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    if (!REPORT_BY_ID[params.rid as string]) return notFound("report", params.rid as string);
    return pdfResponse();
  }),

  http.get("/api/reports/:rid/certificate.pdf", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    if (!REPORT_BY_ID[params.rid as string]) return notFound("report", params.rid as string);
    return pdfResponse();
  }),

  http.get("/api/reports/:rid/manifest", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    const report = REPORT_BY_ID[params.rid as string];
    if (!report) return notFound("report", params.rid as string);
    return HttpResponse.json(buildMockManifest(report));
  }),

  http.post("/api/cases/:cid/assistant/draft", async ({ request }) => {
    if (!currentUsername()) return unauthenticated();
    const body = (await request.json().catch(() => null)) as { facts?: { id?: unknown; text?: unknown }[] } | null;
    const facts = (body?.facts ?? []).filter(
      (f): f is { id: string; text: string } => typeof f.id === "string" && typeof f.text === "string",
    );
    if (facts.length === 0) {
      return HttpResponse.json(
        { error: { code: "validation_error", message: "facts must be a non-empty list.", details: {} } },
        { status: 422 },
      );
    }
    const ids = new Set(facts.map((f) => f.id));
    let sentences: DraftSentenceOut[] = MOCK_DRAFT_SENTENCES.filter((s) => s.evidence_ids.every((id) => ids.has(id)));
    if (sentences.length === 0) {
      // Facts don't line up with the fixture: echo the first facts verbatim, each citing itself,
      // so the response still satisfies the validator's rules (cited id exists, numbers in fact).
      sentences = facts.slice(0, 3).map((f) => ({ text: f.text, evidence_ids: [f.id] }));
    }
    return HttpResponse.json(sentences);
  }),
];
