import { http, HttpResponse } from "msw";
import { LLM_USAGE } from "./settings-fixtures";

function currentUsername(): string | null {
  const cookie = typeof document !== "undefined" ? document.cookie : "";
  const match = /pramaan_session=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Settings (F4) handler for `GET /api/llm/usage`. Always returns the fixture rows regardless of the
 * shared HEALTH fixture's `llm_enabled` value, so the budget meter has realistic historical spend
 * to render (in its inactive state when the LLM is off). NOTE: the real backend instead answers 404 `llm_disabled`
 * when the LLM is off; the Settings screen handles both (404 = "no usage available").
 */
export const settingsHandlers = [
  http.get("/api/llm/usage", () => {
    if (!currentUsername()) {
      return HttpResponse.json(
        { error: { code: "unauthenticated", message: "Sign in required.", details: {} } },
        { status: 401 },
      );
    }
    return HttpResponse.json(LLM_USAGE);
  }),
];
