import { http, HttpResponse } from "msw";
import { DEMO_ASSISTANT_RESPONSE, LLM_ENABLED_DEMO_MARKER } from "./assistant-fixtures";

function unauthenticated() {
  return HttpResponse.json(
    { error: { code: "unauthenticated", message: "Sign in required.", details: {} } },
    { status: 401 },
  );
}

function currentUsername(): string | null {
  const cookie = typeof document !== "undefined" ? document.cookie : "";
  const match = /pramaan_session=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * "Ask about this case" MSW handlers (apps/api/pramaan_api/routers/assistant.py).
 *
 * Convention (same escape-hatch technique as the other feature mocks; never mutate the shared
 * `HEALTH` fixture): by default the route mirrors the real backend with the LLM feature off —
 * `404 {"error": {"code": "llm_disabled"}}` — so mock mode exercises the realistic default UI
 * state. A question containing the literal `__llm_enabled_demo__` bypasses that and returns a
 * deterministic `AssistantQueryResponse`, letting e2e/visual QA reach the success UI path.
 */
export const assistantHandlers = [
  http.post("/api/cases/:cid/assistant/query", async ({ request }) => {
    if (!currentUsername()) return unauthenticated();
    const body = (await request.json().catch(() => null)) as { question?: unknown } | null;
    const question = typeof body?.question === "string" ? body.question : "";
    if (question.includes(LLM_ENABLED_DEMO_MARKER)) return HttpResponse.json(DEMO_ASSISTANT_RESPONSE);
    return HttpResponse.json(
      { error: { code: "llm_disabled", message: "The LLM assistant is disabled on this server.", details: {} } },
      { status: 404 },
    );
  }),
];
