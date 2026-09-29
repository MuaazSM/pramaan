import { setupServer } from "msw/node";
import { handlers } from "./handlers";

/** Used by Vitest (jsdom has no Service Worker) and Playwright can reuse the same handlers list. */
export const server = setupServer(...handlers);
