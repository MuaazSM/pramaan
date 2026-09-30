/**
 * Classified API errors for the empty/error/loading states audit (F5 — docs/PROGRESS.md
 * "UI fix list for F5/I1" + the F5 task brief's explicit "API down, 401, 403 reviewer role" list).
 *
 * Before this, every screen's `queryFn` did `if (error || !data) throw new Error("<noun>
 * unavailable")` (or, worse, silently fell back to `.data ?? []`/`?? undefined`), so a 401
 * (session expired), a 403 (reviewer role hit an examiner-only read), a 500, and the API being
 * completely unreachable all rendered the exact same generic "could not be found" / empty-looking
 * screen. That's actively misleading in a forensic tool: an examiner seeing "No findings" should
 * be able to trust that means zero findings, not "the request 403'd". `ApiError` carries the HTTP
 * status (or `null` for a network-level failure — fetch threw, no `response` at all) so
 * `<QueryErrorState>` (query-error-state.tsx) can render the right icon/copy for each case.
 */
export class ApiError extends Error {
  readonly status: number | null;

  constructor(status: number | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Builds an `ApiError` from an `openapi-fetch` response. `response` is `undefined` when the
 * `fetch` itself failed (network down / API unreachable, no HTTP status to read at all) — that's
 * the `status: null` "can't reach the API" case, distinct from a real 4xx/5xx from a live server.
 */
export function errorFromResponse(response: Response | undefined, fallbackMessage: string): ApiError {
  if (!response) return new ApiError(null, fallbackMessage);
  return new ApiError(response.status, fallbackMessage);
}

/** Query-key-friendly discriminator used by `<QueryErrorState>` and any bespoke error copy. */
export type ErrorKind = "network" | "unauthorized" | "forbidden" | "not_found" | "server" | "unknown";

export function classifyError(error: unknown): ErrorKind {
  if (!(error instanceof ApiError)) return "unknown";
  if (error.status === null) return "network";
  if (error.status === 401) return "unauthorized";
  if (error.status === 403) return "forbidden";
  if (error.status === 404) return "not_found";
  if (error.status >= 500) return "server";
  return "unknown";
}
