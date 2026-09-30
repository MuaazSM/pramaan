import type { components } from "@/api/schema.gen";

type AssistantQueryResponse = components["schemas"]["AssistantQueryResponse"];

/** Question substring that bypasses the default 404 `llm_disabled` — see assistant-handlers.ts. */
export const LLM_ENABLED_DEMO_MARKER = "__llm_enabled_demo__";

/**
 * Deterministic "what the model proposed" response for the escape-hatch question. Synthetic data
 * only (CLAUDE.md rule 7); the filter mirrors the demo case's channel-3 deletion window and the
 * result rows mirror the generic shape of the backend's `search_evidence` results.
 */
export const DEMO_ASSISTANT_RESPONSE: AssistantQueryResponse = {
  filter: {
    channels: [3],
    deleted_only: true,
    source: "carved",
    from_ist: "2026-03-13T01:00:00+05:30",
    to_ist: "2026-03-13T03:00:00+05:30",
  },
  result_count: 3,
  results: [
    { kind: "frame", frame_id: "frm_ch3_0240", channel: 3, ts_header_us: 1773345600000000, source: "carved", deleted: true },
    { kind: "frame", frame_id: "frm_ch3_0241", channel: 3, ts_header_us: 1773345900000000, source: "carved", deleted: true },
    { kind: "frame", frame_id: "frm_ch3_0242", channel: 3, ts_header_us: 1773346200000000, source: "carved", deleted: true },
  ],
};
