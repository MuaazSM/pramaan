import { http, HttpResponse } from "msw";
import type { components } from "@/api/schema.gen";
import {
  USERS,
  CASES,
  DEMO_CASE,
  EVIDENCE_BY_CASE,
  JOBS_BY_CASE,
  AUDIT_BY_CASE,
  HEALTH,
  FS_TREE,
  FINGERPRINT_BY_EVIDENCE,
  RECORDINGS_BY_CASE,
  DELETIONS_BY_CASE,
  CLOCK_MODELS_BY_CASE,
  LOG_EVENTS_BY_CASE,
  INFERRED_LAYOUT_BY_EVIDENCE,
  findEvidence,
  findEvidenceCaseId,
} from "./fixtures";
import { wsHandlers } from "./ws-handlers";
// Review workspace (F3a) handlers/fixtures — timeline, motion, frames, clip streaming. Kept in
// their own module (review-handlers.ts/review-fixtures.ts) per F3a's ownership; spread into the
// shared array below rather than growing this file's own fixture imports.
import { reviewHandlers } from "./review-handlers";

type Job = components["schemas"]["Job"];
type JobStage = components["schemas"]["JobStage"];

const SESSION_COOKIE = "pramaan_session";

function currentUsername(_request: Request): string | null {
  // Handlers run in the page's main thread (MSW forwards intercepted requests here over
  // postMessage), so document.cookie is readable even though the browser does not expose the
  // Cookie header on the Service Worker's intercepted Request object (a Fetch/SW spec
  // restriction — see https://github.com/mswjs/msw/issues/1691).
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

/** MSW handlers backing every route the F1 screens + F2 (evidence detail/recordings/findings) call. */
const httpHandlers = [
  http.get("/api/system/health", () => HttpResponse.json(HEALTH)),

  http.post("/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as { username: string; password: string };
    const record = USERS[body.username];
    if (!record || record.password !== body.password) {
      return HttpResponse.json(
        { error: { code: "invalid_credentials", message: "Username or password is incorrect.", details: {} } },
        { status: 401 },
      );
    }
    return HttpResponse.json(record.me, {
      headers: { "Set-Cookie": `${SESSION_COOKIE}=${encodeURIComponent(body.username)}; Path=/; SameSite=Strict` },
    });
  }),

  http.post("/api/auth/logout", () =>
    HttpResponse.json(null, {
      status: 204,
      headers: { "Set-Cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0` },
    }),
  ),

  http.get("/api/me", ({ request }) => {
    const username = currentUsername(request);
    const record = username ? USERS[username] : undefined;
    if (!record) return unauthenticated();
    return HttpResponse.json(record.me);
  }),

  http.get("/api/cases", ({ request }) => {
    if (!currentUsername(request)) return unauthenticated();
    return HttpResponse.json(CASES);
  }),

  http.get("/api/cases/:cid", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const found = CASES.find((c) => c.id === params.cid);
    if (!found) return HttpResponse.json({ error: { code: "not_found", message: "Case not found.", details: {} } }, { status: 404 });
    return HttpResponse.json(found);
  }),

  http.get("/api/cases/:cid/evidence", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    return HttpResponse.json(EVIDENCE_BY_CASE[params.cid as string] ?? []);
  }),

  http.post("/api/cases/:cid/evidence", async ({ request, params }) => {
    const username = currentUsername(request);
    if (!username) return unauthenticated();
    const body = (await request.json()) as { path: string; label: string };
    const list = EVIDENCE_BY_CASE[params.cid as string] ?? [];
    const created = {
      id: `ev_${Math.abs(hashCode(body.path)).toString(36)}`,
      path: body.path,
      format: body.path.toLowerCase().endsWith(".e01") ? ("e01" as const) : ("raw" as const),
      size_bytes: 500_000_000_000,
      sha256: "b2e5c8f1a4d7e0b3c6f9a2d5e8b1c47a3d6f9c2b5e8f1a4d7c0b3e6f9a2d5c81",
      md5: "5c8f1a4d7e0b3c6f9a2d5e8b1c47a3d6",
      acquired_utc: "2026-03-30T06:00:00Z",
      verified: false,
    };
    list.push(created);
    EVIDENCE_BY_CASE[params.cid as string] = list;
    return HttpResponse.json(created, { status: 201 });
  }),

  http.get("/api/cases/:cid/jobs", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    return HttpResponse.json(JOBS_BY_CASE[params.cid as string] ?? []);
  }),

  http.get("/api/jobs/:jid", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const all = Object.values(JOBS_BY_CASE).flat();
    const job = all.find((j) => j.id === params.jid);
    if (!job) return HttpResponse.json({ error: { code: "not_found", message: "Job not found.", details: {} } }, { status: 404 });
    return HttpResponse.json(job);
  }),

  http.get("/api/cases/:cid/audit", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const u = new URL(request.url);
    const limit = Number(u.searchParams.get("limit") ?? "25");
    const cursor = Number(u.searchParams.get("cursor") ?? "0");
    const entries = AUDIT_BY_CASE[params.cid as string] ?? [];
    const items = entries.slice(cursor, cursor + limit);
    const next = cursor + limit < entries.length ? String(cursor + limit) : null;
    return HttpResponse.json({ items, next_cursor: next });
  }),

  http.get("/api/cases/:cid/audit/verify", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const entries = AUDIT_BY_CASE[params.cid as string] ?? [];
    const last = entries[entries.length - 1];
    return HttpResponse.json({ ok: true, length: entries.length, head_hash: last?.entry_hash ?? null, first_bad_seq: null });
  }),

  http.get("/api/evidence/:eid/fingerprint", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    return HttpResponse.json(FINGERPRINT_BY_EVIDENCE[params.eid as string] ?? []);
  }),

  http.get("/api/cases/:cid/recordings", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const u = new URL(request.url);
    let list = RECORDINGS_BY_CASE[params.cid as string] ?? [];
    const channel = u.searchParams.get("channel");
    const source = u.searchParams.get("source");
    const deleted = u.searchParams.get("deleted");
    const from = u.searchParams.get("from");
    const to = u.searchParams.get("to");
    if (channel != null) list = list.filter((r) => r.channel === Number(channel));
    if (source != null) list = list.filter((r) => r.source === source);
    if (deleted != null) list = list.filter((r) => r.deleted === (deleted === "true"));
    if (from != null) list = list.filter((r) => (r.end_ts_us ?? 0) >= Number(from));
    if (to != null) list = list.filter((r) => (r.start_ts_us ?? 0) <= Number(to));
    return HttpResponse.json(list);
  }),

  http.get("/api/recordings/:rid", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const all = Object.values(RECORDINGS_BY_CASE).flat();
    const found = all.find((r) => r.id === params.rid);
    if (!found) return HttpResponse.json({ error: { code: "not_found", message: "Recording not found.", details: {} } }, { status: 404 });
    return HttpResponse.json(found);
  }),

  http.get("/api/cases/:cid/deletions", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    return HttpResponse.json(DELETIONS_BY_CASE[params.cid as string] ?? []);
  }),

  http.get("/api/cases/:cid/clock-models", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    return HttpResponse.json(CLOCK_MODELS_BY_CASE[params.cid as string] ?? []);
  }),

  http.get("/api/cases/:cid/log-events", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const u = new URL(request.url);
    const kind = u.searchParams.get("kind");
    let list = LOG_EVENTS_BY_CASE[params.cid as string] ?? [];
    if (kind) list = list.filter((e) => e.kind === kind);
    return HttpResponse.json(list);
  }),

  http.get("/api/fs/browse", ({ request }) => {
    if (!currentUsername(request)) return unauthenticated();
    const u = new URL(request.url);
    const path = u.searchParams.get("path") ?? "/evidence";
    return HttpResponse.json(FS_TREE[path] ?? []);
  }),

  // --- F2: evidence detail (identification, pipeline, inferred layout) -------------------------

  http.get("/api/evidence/:eid", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const found = findEvidence(params.eid as string);
    if (!found) return HttpResponse.json({ error: { code: "not_found", message: "Evidence not found.", details: {} } }, { status: 404 });
    return HttpResponse.json(found);
  }),

  http.get("/api/evidence/:eid/inferred-layout", ({ request, params }) => {
    if (!currentUsername(request)) return unauthenticated();
    const layout = INFERRED_LAYOUT_BY_EVIDENCE[params.eid as string];
    if (!layout) return HttpResponse.json({ error: { code: "not_found", message: "No inferred layout for this image.", details: {} } }, { status: 404 });
    return HttpResponse.json(layout);
  }),

  http.post("/api/inferred-layouts/:lid/confirm", ({ request, params }) => {
    const username = currentUsername(request);
    if (!username) return unauthenticated();
    const role = USERS[username]?.me.role;
    if (role !== "examiner" && role !== "admin") {
      return HttpResponse.json({ error: { code: "forbidden", message: "Reviewers cannot confirm layouts.", details: {} } }, { status: 403 });
    }
    const layout = Object.values(INFERRED_LAYOUT_BY_EVIDENCE).find((l) => l.id === params.lid);
    if (!layout) return HttpResponse.json({ error: { code: "not_found", message: "Layout not found.", details: {} } }, { status: 404 });
    layout.confirmed_by = username;
    return HttpResponse.json(layout);
  }),

  http.post("/api/evidence/:eid/scan", ({ request, params }) => {
    const username = currentUsername(request);
    if (!username) return unauthenticated();
    const role = USERS[username]?.me.role;
    if (role !== "examiner" && role !== "admin") {
      return HttpResponse.json({ error: { code: "forbidden", message: "Reviewers cannot run scans.", details: {} } }, { status: 403 });
    }
    const eid = params.eid as string;
    const cid = findEvidenceCaseId(eid);
    if (!cid) return HttpResponse.json({ error: { code: "not_found", message: "Evidence not found.", details: {} } }, { status: 404 });
    const now = "2026-03-30T06:30:00Z";
    const stageNames = [
      "hash_verify",
      "fingerprint",
      "parse_index",
      "infer_layout",
      "carve",
      "frame_index",
      "logs",
      "deletion_verdict",
      "clips",
      "timeline",
      "motion",
    ];
    const stages: JobStage[] = stageNames.map((name) => ({ name, status: "pending", pct: 0, message: null }));
    const job: Job = {
      id: `job_scan_${Math.abs(hashCode(`${eid}_${Object.values(JOBS_BY_CASE).flat().length}`)).toString(36)}`,
      case_id: cid,
      evidence_id: eid,
      kind: "scan",
      status: "running",
      pct: 0,
      created_utc: now,
      updated_utc: now,
      log_lines: [],
      stages,
    };
    JOBS_BY_CASE[cid] = [...(JOBS_BY_CASE[cid] ?? []), job];
    return HttpResponse.json(job, { status: 202 });
  }),
];

export const handlers = [...httpHandlers, ...reviewHandlers, ...wsHandlers];

function hashCode(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}

export { DEMO_CASE };
