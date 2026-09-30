import { http, HttpResponse } from "msw";
import type { components } from "@/api/schema.gen";
import { AUDIT_BY_CASE } from "./fixtures";
import { ANCHORS_BY_CASE, makeAnchor } from "./custody-fixtures";

type AnchorCreate = components["schemas"]["AnchorCreate"];

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
 * Custody screen (F4) anchors handlers. Audit list + verify handlers already live in the shared
 * handlers.ts (F1); only anchors are added here. Mirrors the real backend's behaviour
 * (apps/api/pramaan_api/real/store.py `create_anchor`): an anchor always spans first..head of the
 * chain, and `backend: "fabric"` returns a clean 501 `not_implemented` (FabricAnchor is
 * interface-only). Created anchors are held in module memory for the page session.
 */
const created: Record<string, typeof ANCHORS_BY_CASE[string]> = {};

function anchorsFor(cid: string) {
  return [...(ANCHORS_BY_CASE[cid] ?? []), ...(created[cid] ?? [])];
}

export const custodyHandlers = [
  http.get("/api/cases/:cid/anchors", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    return HttpResponse.json(anchorsFor(params.cid as string));
  }),

  http.post("/api/cases/:cid/anchors", async ({ request, params }) => {
    if (!currentUsername()) return unauthenticated();
    const cid = params.cid as string;
    const body = (await request.json().catch(() => ({}))) as AnchorCreate;
    if (body.backend === "fabric") {
      return HttpResponse.json(
        {
          error: {
            code: "not_implemented",
            message: "FabricAnchor is not implemented in this build; use the local anchor backend.",
            details: {},
          },
        },
        { status: 501 },
      );
    }
    const entries = AUDIT_BY_CASE[cid] ?? [];
    if (entries.length === 0) {
      return HttpResponse.json(
        { error: { code: "bad_request", message: "Cannot anchor an empty custody chain.", details: {} } },
        { status: 400 },
      );
    }
    const list = anchorsFor(cid);
    const anchor = makeAnchor(cid, list.length + 1, entries[0].seq, entries[entries.length - 1].seq, entries[entries.length - 1].ts_utc);
    (created[cid] ??= []).push(anchor);
    return HttpResponse.json(anchor, { status: 201 });
  }),
];
