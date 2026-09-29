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

export const isMockMode = (): boolean =>
  import.meta.env.VITE_MOCK === "1" || import.meta.env.MODE === "test";
