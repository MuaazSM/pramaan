import type { components } from "@/api/schema.gen";
import { fakeHex } from "./custody-fixtures";

type LlmUsageEntry = components["schemas"]["LlmUsageEntry"];

function row(n: number, model: string, inTok: number, outTok: number, cost: number, ts: string): LlmUsageEntry {
  return {
    id: `llm_${fakeHex(`usage:${n}`, 12)}`,
    model,
    input_tokens: inTok,
    output_tokens: outTok,
    cost_usd: cost,
    prompt_sha256: fakeHex(`prompt:${n}`),
    response_sha256: fakeHex(`response:${n}`),
    created_utc: ts,
  };
}

/** Deterministic LLM usage rows (total $2.49 — well under the $60 total / $5 per-case default caps). */
export const LLM_USAGE: LlmUsageEntry[] = [
  row(1, "claude-sonnet-4-5", 3120, 410, 0.0155, "2026-03-13T09:41:12Z"),
  row(2, "claude-sonnet-4-5", 2890, 388, 0.0145, "2026-03-13T09:43:50Z"),
  row(3, "claude-opus-4-1", 9410, 1260, 0.2352, "2026-03-14T11:02:31Z"),
  row(4, "claude-sonnet-4-5", 4275, 902, 0.0263, "2026-03-15T14:20:07Z"),
  row(5, "claude-opus-4-1", 18820, 2140, 0.4425, "2026-03-16T10:11:45Z"),
  row(6, "claude-opus-4-1", 41200, 3980, 0.9165, "2026-03-17T16:37:02Z"),
  row(7, "claude-haiku-4-5", 6100, 720, 0.0097, "2026-03-17T16:52:18Z"),
  row(8, "claude-opus-4-1", 22400, 2860, 0.8298, "2026-03-18T05:58:40Z"),
];
