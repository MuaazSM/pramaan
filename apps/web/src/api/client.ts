import createClient from "openapi-fetch";
import type { paths } from "./schema.gen";

/**
 * Typed API client generated from apps/api/openapi.json (see package.json's `gen:api`).
 * Never hand-write response/request types — regenerate `schema.gen.ts` instead.
 *
 * Mock mode (`VITE_MOCK=1`, default in `pnpm dev:mock`) is served by MSW (src/mocks/), which
 * intercepts `fetch` at the network layer, so this client talks to `/api` in both modes.
 */
export const api = createClient<paths>({ baseUrl: "/" });

const CSRF_COOKIE_NAME = "pramaan_csrf";
const CSRF_HEADER_NAME = "x-csrf-token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Real-mode CSRF wiring: `require_csrf` (apps/api/pramaan_api/deps.py) double-submit-checks the
 * `pramaan_csrf` cookie (set non-HttpOnly on login, see `routers/auth.py`) against an
 * `X-CSRF-Token` header on every mutating request — a no-op in stub mode, enforced in real mode
 * (docs/progress/B1.md "Decisions"). Attached here, once, as client middleware, so every screen's
 * `api.POST/PUT/PATCH/DELETE(...)` call gets it automatically instead of every feature
 * reimplementing its own cookie-reading helper (found duplicated ad hoc while wiring real mode for
 * this task — centralised instead of left as N copies).
 */
api.use({
  onRequest({ request }) {
    if (!MUTATING_METHODS.has(request.method)) return undefined;
    const token = readCookie(CSRF_COOKIE_NAME);
    if (!token) return undefined;
    request.headers.set(CSRF_HEADER_NAME, token);
    return request;
  },
});

export const isMockMode = (): boolean =>
  import.meta.env.VITE_MOCK === "1" || import.meta.env.MODE === "test";
