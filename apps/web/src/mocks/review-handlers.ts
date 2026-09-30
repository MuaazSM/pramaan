import { http, HttpResponse } from "msw";
import {
  TIMELINE_BY_CASE,
  MOTION_BY_CASE,
  DETECTIONS_BY_CASE,
  FRAMES_BY_CASE,
  CLIP_URL_BY_CHANNEL,
} from "./review-fixtures";

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
 * Review workspace (F3a) MSW handlers — timeline, motion, detections, frames, clip streaming.
 * (Log events are handled by the shared handlers.ts + fixtures.ts — see review-fixtures.ts's
 * note.) Spread into the shared `handlers` array in ./handlers.ts (see that file's import).
 * Kept in its own module per this task's ownership of "MSW handlers/fixtures for timeline/clip
 * data" as a clearly separated section rather than growing the shared handlers.ts file directly.
 */
export const reviewHandlers = [
  http.get("/api/cases/:cid/timeline", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    const data = TIMELINE_BY_CASE[params.cid as string];
    if (!data) return HttpResponse.json({ channels: [], markers: [], events: [] });
    return HttpResponse.json(data);
  }),

  http.get("/api/cases/:cid/motion", ({ request, params }) => {
    if (!currentUsername()) return unauthenticated();
    const u = new URL(request.url);
    const channel = u.searchParams.get("channel");
    let items = MOTION_BY_CASE[params.cid as string] ?? [];
    if (channel != null) items = items.filter((m) => m.channel === Number(channel));
    return HttpResponse.json(items);
  }),

  http.get("/api/cases/:cid/detections", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    return HttpResponse.json(DETECTIONS_BY_CASE[params.cid as string] ?? []);
  }),

  http.get("/api/cases/:cid/frames", ({ request, params }) => {
    if (!currentUsername()) return unauthenticated();
    const u = new URL(request.url);
    const channel = u.searchParams.get("channel");
    const source = u.searchParams.get("source");
    const deleted = u.searchParams.get("deleted");
    const from = u.searchParams.get("from");
    const to = u.searchParams.get("to");
    let items = FRAMES_BY_CASE[params.cid as string] ?? [];
    if (channel != null) items = items.filter((f) => f.channel === Number(channel));
    if (source) items = items.filter((f) => f.source === source);
    if (deleted != null) items = items.filter((f) => f.deleted === (deleted === "true"));
    if (from != null) items = items.filter((f) => (f.ts_header_us ?? 0) >= Number(from));
    if (to != null) items = items.filter((f) => (f.ts_header_us ?? 0) <= Number(to));
    return HttpResponse.json(items);
  }),

  http.get("/api/frames/:fid", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    const all = Object.values(FRAMES_BY_CASE).flat();
    const frame = all.find((f) => f.frame_id === params.fid);
    if (!frame) return HttpResponse.json({ error: { code: "not_found", message: "Frame not found.", details: {} } }, { status: 404 });
    return HttpResponse.json(frame);
  }),

  // Real shape: binary video/mp4 bytes, Range-aware. Mock convention: clip ids are `clip_ch{n}`;
  // the video grid resolves the static asset URL directly (see clip-mapping.ts) rather than
  // calling this route (avoids an extra hop for a file already servable by Vite's static
  // middleware) — this handler exists so the route's *shape* (a redirect to real bytes) is still
  // exercised if something does call it directly (e.g. a future Playwright network assertion).
  http.get("/api/clips/:clipId/stream", ({ params }) => {
    if (!currentUsername()) return unauthenticated();
    const match = /^clip_ch(\d)$/.exec(String(params.clipId));
    const channel = match ? Number(match[1]) : null;
    const url = channel != null ? CLIP_URL_BY_CHANNEL[channel] : undefined;
    if (!url) return HttpResponse.json({ error: { code: "not_found", message: "Clip not found.", details: {} } }, { status: 404 });
    return HttpResponse.redirect(url, 302);
  }),
];
