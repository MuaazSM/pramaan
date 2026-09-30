/**
 * Review workspace (F3a) mock fixtures — timeline, frames, motion, log events, clip mapping.
 *
 * Kept in its own file (not appended to fixtures.ts, which F1/F2 also depend on) per this task's
 * ownership: "MSW handlers/fixtures for timeline/clip data (in new files or a clearly separated
 * section of the shared mocks folder)". Deterministic: every generator below is a pure function
 * of fixed constants (no Date.now()/Math.random()), matching the repo-wide determinism rule.
 *
 * Unit convention: every timestamp here is "normalised microseconds since the Unix epoch"
 * (matches `ts_norm_us` on TimelineMarker and the *_ts_us fields elsewhere in the schema) over a
 * clean 24h demo window, 2026-03-12T00:00:00Z .. 2026-03-13T00:00:00Z. This is independent of
 * fixtures.ts's RECORDINGS_BY_CASE/DELETIONS_BY_CASE (which use small relative-second offsets,
 * not epoch time) — the two are not cross-referenced numerically in this task; unifying them
 * behind one shared "case acquisition start" constant is a follow-up once a later task needs
 * the Review and Findings/Recordings screens to point at the exact same instant.
 */
import type { components } from "@/api/schema.gen";
import { DEMO_CASE, CHANNELS } from "./fixtures";

type TimelineResponse = components["schemas"]["TimelineResponse"];
type ChannelTimeline = components["schemas"]["ChannelTimeline"];
type TimelineMarker = components["schemas"]["TimelineMarker"];
type TimelineEvent = components["schemas"]["TimelineEvent"];
type FrameRef = components["schemas"]["FrameRef"];
type MotionSegment = components["schemas"]["MotionSegment"];

const HOUR_US = 3600 * 1_000_000;
const MIN_US = 60 * 1_000_000;

export const REVIEW_RANGE_START_US = Date.parse("2026-03-12T00:00:00.000Z") * 1000;
export const REVIEW_RANGE_END_US = Date.parse("2026-03-13T00:00:00.000Z") * 1000;

/** Deterministic PRNG (mulberry32) — same fixture bytes on every run, per CLAUDE.md rule 5. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CHANNEL_NUMBERS = [1, 2, 3, 4] as const;

// Channel 3 (Counter) has the 13h "format" deletion window, mirroring fixtures.ts's finding.
const DELETION_START_US = REVIEW_RANGE_START_US + 20 * HOUR_US;
const DELETION_END_CLAMPED_US = Math.min(REVIEW_RANGE_END_US, DELETION_START_US + 13 * HOUR_US);

function buildChannel(channel: number, label: string, colorIndex: number): ChannelTimeline {
  const rng = mulberry32(1000 + channel);
  const coverage: ChannelTimeline["coverage"] = [];
  const deleted: ChannelTimeline["deleted"] = [];
  const motion: ChannelTimeline["motion"] = [];

  const segStep = 15 * MIN_US;
  for (let us = REVIEW_RANGE_START_US; us < REVIEW_RANGE_END_US; us += segStep) {
    const inDeletionWindow = channel === 3 && us >= DELETION_START_US && us < DELETION_END_CLAMPED_US;
    const source = inDeletionWindow ? "carved" : rng() < 0.04 ? "inferred" : "index";
    coverage.push([us, us + segStep, source]);
    if (inDeletionWindow) deleted.push([us, us + segStep, "format"]);
  }

  for (let us = REVIEW_RANGE_START_US; us < REVIEW_RANGE_END_US; us += MIN_US) {
    // A few gentle activity bumps through the day, deterministic per channel.
    const base = 0.08 + 0.05 * Math.sin(us / (2 * HOUR_US) + channel);
    const bump = rng() < 0.02 ? 0.6 + 0.35 * rng() : 0;
    motion.push([us, Math.max(0, Math.min(1, base + bump))]);
  }

  return {
    image_id: "ev_hiksim01",
    channel,
    label,
    color_token: `ch-${colorIndex}`,
    coverage,
    deleted,
    motion,
    clock: {
      confidence: channel === 2 ? 0.88 : 0.97,
      summary: channel === 2 ? "log-anchored, +37s OSD drift" : "log-anchored piecewise linear",
    },
  };
}

export const TIMELINE_MARKERS: TimelineMarker[] = [
  { ts_norm_us: REVIEW_RANGE_START_US + 2 * HOUR_US, kind: "power_on", log_event_id: "log_power_on_001", user: null },
  { ts_norm_us: DELETION_START_US, kind: "hdd_format", log_event_id: "log_hdd_format_001", user: "admin" },
  { ts_norm_us: REVIEW_RANGE_START_US + 2 * HOUR_US + 5 * MIN_US, kind: "time_change", log_event_id: "log_time_change_001", user: "admin" },
  { ts_norm_us: REVIEW_RANGE_START_US + 18 * HOUR_US, kind: "export", log_event_id: "log_export_001", user: "examiner" },
];

// Note: log-event *detail* records (LogEvent, with device offsets etc.) are fixtures.ts's
// LOG_EVENTS_BY_CASE (added alongside this task by the evidence-detail work) and are served by
// the existing `/api/cases/:cid/log-events` handler in handlers.ts — not duplicated here. The
// markers below carry their own `kind`/`user` for the canvas, and reference log_event_id purely
// as a label; resolving that id to full LogEvent detail is the frame-inspector's job (F3b).
export const TIMELINE_EVENTS: TimelineEvent[] = [
  { start: REVIEW_RANGE_START_US + 9 * HOUR_US, end: REVIEW_RANGE_START_US + 9 * HOUR_US + 3 * MIN_US, channels: [1, 2], kind: "co_motion" },
];

export const TIMELINE_BY_CASE: Record<string, TimelineResponse> = {
  [DEMO_CASE.id]: {
    channels: CHANNEL_NUMBERS.map((ch, i) => buildChannel(ch, CHANNELS[i]?.label ?? `CH${ch}`, i + 1)),
    markers: TIMELINE_MARKERS,
    events: TIMELINE_EVENTS,
  },
};

export const MOTION_BY_CASE: Record<string, MotionSegment[]> = {
  [DEMO_CASE.id]: CHANNEL_NUMBERS.flatMap((ch) => {
    const rng = mulberry32(2000 + ch);
    const out: MotionSegment[] = [];
    for (let i = 0; i < 6; i++) {
      const start = REVIEW_RANGE_START_US + i * 4 * HOUR_US + Math.floor(rng() * HOUR_US);
      out.push({
        id: `motion_ch${ch}_${i}`,
        image_id: "ev_hiksim01",
        channel: ch,
        start_norm_us: start,
        end_norm_us: start + 90 * 1_000_000,
        peak_score: 0.5 + 0.4 * rng(),
        frames: 12 + Math.floor(rng() * 40),
      });
    }
    return out;
  }),
};

// Detections (BRAND.md §5.1 calls this P2 — "tiny glyphs"); not rendered on the canvas this
// wave, but the endpoint is mocked so the shape is exercised end to end. See docs/progress/F3a.md.
export const DETECTIONS_BY_CASE: Record<string, components["schemas"]["Detection"][]> = {
  [DEMO_CASE.id]: [],
};

/** One sampled FrameRef every 5 minutes per channel — enough for "G" frame-id lookups and frame
 * stepping without shipping an unreasonably large fixture (24h / 5min x 4ch = 1,152 frames). */
function buildFrames(channel: number): FrameRef[] {
  const out: FrameRef[] = [];
  const step = 5 * MIN_US;
  let i = 0;
  for (let us = REVIEW_RANGE_START_US; us < REVIEW_RANGE_END_US; us += step, i++) {
    const deleted = channel === 3 && us >= DELETION_START_US && us < DELETION_END_CLAMPED_US;
    out.push({
      frame_id: `frm_ch${channel}_${String(i).padStart(4, "0")}`,
      image_id: "ev_hiksim01",
      channel,
      stream: "main",
      codec: "h264",
      frame_type: i % 30 === 0 ? "I" : "P",
      header_offset: 4096 + i * 512,
      payload_offset: 4096 + i * 512 + 32,
      payload_len: 18_000 + (i % 7) * 512,
      ts_header_us: us,
      ts_index_us: us,
      width: 1280,
      height: 720,
      source: deleted ? "carved" : "index",
      recording_id: null,
      deleted,
    });
  }
  return out;
}

export const FRAMES_BY_CASE: Record<string, FrameRef[]> = {
  [DEMO_CASE.id]: CHANNEL_NUMBERS.flatMap((ch) => buildFrames(ch)),
};

/** Mock clip: one short deterministic file per channel (see docs/progress/F3a.md "Decisions"). */
export const CLIP_URL_BY_CHANNEL: Record<number, string> = {
  1: "/mocks/clips/ch1.mp4",
  2: "/mocks/clips/ch2.mp4",
  3: "/mocks/clips/ch3.mp4",
  4: "/mocks/clips/ch4.mp4",
};
export const MOCK_CLIP_DURATION_S = 20;
export const MOCK_CLIP_FPS = 10;
