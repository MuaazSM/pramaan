import { useEffect, useState } from "react";
import type { components } from "@/api/schema.gen";

type Job = components["schemas"]["Job"];
type JobStage = components["schemas"]["JobStage"];

export interface PipelineState {
  stages: JobStage[];
  logLines: string[];
  pct: number;
  status: Job["status"];
}

/**
 * Binds a job's pipeline progress to `/api/ws?case_id=` (docs/02-BACKEND.md §7), live-updating a
 * seeded snapshot of `job.stages`/`log_lines`/`pct` as `job.progress`/`job.log`/`job.done`/
 * `job.failed` events arrive. Works in both mock mode (`src/mocks/ws-handlers.ts` intercepts the
 * same `WebSocket` the browser opens) and real mode (the actual FastAPI `/api/ws` socket) — no
 * VITE_MOCK branch needed here, matching every other data hook in this app.
 *
 * Only opens a socket while the seeded job is `queued`/`running`; a `done`/`failed` job renders
 * its last known snapshot with no live connection (nothing left to stream).
 */
export function useJobPipeline(caseId: string | undefined, job: Job | undefined): PipelineState | null {
  const [state, setState] = useState<PipelineState | null>(null);

  useEffect(() => {
    if (!job) {
      setState(null);
      return;
    }
    setState({ stages: job.stages, logLines: job.log_lines, pct: job.pct, status: job.status });
    if (!caseId || (job.status !== "running" && job.status !== "queued")) return;

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${window.location.host}/api/ws?case_id=${encodeURIComponent(caseId)}`);

    socket.onmessage = (event: MessageEvent<string>) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        return;
      }
      if (msg.job_id != null && msg.job_id !== job.id) return; // event belongs to another job in this case
      setState((prev) => {
        const base = prev ?? { stages: job.stages, logLines: job.log_lines, pct: job.pct, status: job.status };
        switch (msg.type) {
          case "job.progress": {
            const stages = upsertStage(base.stages, msg.stage as string, msg.pct as number, msg.message as string);
            const pct = stages.reduce((sum, s) => sum + s.pct, 0) / stages.length;
            return { ...base, stages, pct, status: "running" };
          }
          case "job.log":
            return { ...base, logLines: [...base.logLines, msg.line as string] };
          case "job.done":
            return {
              ...base,
              pct: 100,
              status: "done",
              stages: base.stages.map((s) => (s.status === "pending" ? { ...s, status: "skipped" as const } : s)),
            };
          case "job.failed":
            return { ...base, status: "failed" };
          default:
            return base;
        }
      });
    };

    return () => socket.close();
    // job.stages/job.log_lines/job.pct are only used as the seed on (re)connect, keyed by job.id —
    // re-running for every poll of the parent query would tear the socket down mid-stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status, caseId]);

  return state;
}

function upsertStage(stages: JobStage[], name: string, pct: number, message: string): JobStage[] {
  const status: JobStage["status"] = pct >= 100 ? "done" : "running";
  const idx = stages.findIndex((s) => s.name === name);
  if (idx === -1) return [...stages, { name, status, pct, message }];
  const next = [...stages];
  next[idx] = { ...next[idx], status, pct, message };
  return next;
}
