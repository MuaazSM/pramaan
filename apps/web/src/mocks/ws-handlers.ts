import { ws } from "msw";
import { JOBS_BY_CASE, DEMO_CASE } from "./fixtures";

/**
 * Mock `/api/ws?case_id=` — the live job-events socket the evidence-detail pipeline panel binds
 * to (docs/02-BACKEND.md §7, replicated from `apps/api/pramaan_api/ws.py`'s `STUB_MODE=1`
 * sequence: `job.progress` → `job.log` → `evidence.verified` → `audit.appended` → `job.done`).
 * Scoped to whichever job in the requested case currently has `status: "running"` (falls back to
 * the case's first job), same as the real stub picking `next(iter(store.DATA.jobs.values()))`.
 *
 * `msw`'s `ws` namespace intercepts real `WebSocket` connections (browser: via the service
 * worker; Node/Vitest: via `msw/node`'s interceptor) — no separate "mock vs real" branch is
 * needed in the client, matching every other MSW handler in this folder.
 */
const STEP_DELAY_MS = 25;

type WsEvent =
  | { type: "job.progress"; job_id: string; stage: string; pct: number; throughput_mbps: number; eta_s: number; message: string }
  | { type: "job.log"; job_id: string; level: "info" | "warn" | "error"; line: string }
  | { type: "evidence.verified"; evidence_id: string; sha256: string; match: boolean }
  | { type: "audit.appended"; seq: number; entry_hash: string; action: string }
  | { type: "job.done"; job_id: string; summary: Record<string, number> }
  | { type: "job.failed"; job_id: string; error: { code: string; message: string } };

function buildEvents(jobId: string, evidenceId: string | null): WsEvent[] {
  const stages: [string, number, string][] = [
    ["hash_verify", 100, "Hashes confirmed"],
    ["fingerprint", 100, "Vendor identification complete"],
    ["parse_index", 100, "Channel table parsed"],
    ["infer_layout", 100, "Layout inference complete"],
    ["carve", 62, "Carving unindexed space 1.2/1.9 GiB"],
    ["carve", 100, "Carve complete: 214 recovered frames"],
    ["frame_index", 100, "180 frames indexed"],
    ["logs", 100, "8 device log events parsed"],
    ["deletion_verdict", 100, "1 deletion finding recorded"],
    ["clips", 100, "60 stream-copied proxies rendered"],
    ["timeline", 100, "4-clock model built, 1 time-change marker"],
    ["motion", 100, "12 motion segments detected"],
  ];
  const events: WsEvent[] = [];
  for (const [stage, pct, message] of stages) {
    events.push({ type: "job.progress", job_id: jobId, stage, pct, throughput_mbps: 612.3, eta_s: Math.max(0, Math.round(100 - pct)), message });
    events.push({ type: "job.log", job_id: jobId, level: "info", line: message });
  }
  if (evidenceId) {
    events.push({ type: "evidence.verified", evidence_id: evidenceId, sha256: "a41f09c2b8d3e6710f4c9a2b5e8d1f0c3a6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d", match: true });
  }
  events.push({ type: "audit.appended", seq: 129, entry_hash: "audit_seq129_demo_hash", action: "job.scan.completed" });
  events.push({ type: "job.done", job_id: jobId, summary: { recordings: 60, recovered_frames: 214, deletions: 1 } });
  return events;
}

export const wsLink = ws.link("/api/ws");

export const wsHandlers = [
  wsLink.addEventListener("connection", ({ client }) => {
    const url = new URL(client.url);
    const caseId = url.searchParams.get("case_id") ?? DEMO_CASE.id;
    const jobs = JOBS_BY_CASE[caseId] ?? [];
    // Prefer the most recently created running job (e.g. one just started from "Run scan") over
    // an older still-running one, so the panel that triggered it is the one that lights up.
    const job = [...jobs].reverse().find((j) => j.status === "running") ?? jobs[jobs.length - 1];
    if (!job) {
      client.close();
      return;
    }
    const events = buildEvents(job.id, job.evidence_id);
    let i = 0;
    const timer = setInterval(() => {
      const event = events[i];
      if (!event) {
        clearInterval(timer);
        client.close();
        return;
      }
      client.send(JSON.stringify(event));
      i += 1;
    }, STEP_DELAY_MS);
  }),
];
