/**
 * Double-submit CSRF header for mutating requests in real mode (docs/02-BACKEND.md §11): login
 * sets a readable `pramaan_csrf` cookie which must be echoed in `X-CSRF-Token`. Harmless in mock
 * mode (no such cookie -> empty headers). Local to this feature — the shared client does not send
 * it yet (see the F4 report's cross-workstream note).
 */
export function csrfHeaders(): Record<string, string> {
  const match = /(?:^|;\s*)pramaan_csrf=([^;]+)/.exec(typeof document !== "undefined" ? document.cookie : "");
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

/** Pulls a human message out of the API's `{ error: { message } }` envelope (or FastAPI's 422 shape). */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const e = error as { error?: { message?: unknown }; detail?: unknown };
    if (typeof e.error?.message === "string") return e.error.message;
    if (Array.isArray(e.detail) && e.detail.length > 0) {
      const first = e.detail[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  return fallback;
}
