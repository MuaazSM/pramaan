/**
 * Plain-language helpers for the F7 "story first, bytes on demand" pass (docs/progress/F7.md).
 * These sit next to `format.ts` (which renders exact values) — this file turns already-formatted
 * or raw machine strings into sentences a first-time viewer (a judge, an investigator) can read
 * without training. Every function is pure and takes only fields the API already returns; nothing
 * here calls the network. Raw values are never discarded — callers keep them available in a
 * "Technical details" disclosure or a tooltip, this module just picks what leads.
 */
import { formatBytes, formatDuration, formatTimecode, formatTimecodeUs } from "./format";

/** Last path segment, so an evidence file reads by name, never by its full host path. */
export function fileName(path: string): string {
  const cleaned = path.replace(/[/\\]+$/, "");
  const parts = cleaned.split(/[/\\]/);
  return parts[parts.length - 1] || path;
}

/** "300 frames" / "1 frame" — a count with its unit, never a bare number. */
export function countWithUnit(n: number, unit: string, plural = `${unit}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? unit : plural}`;
}

const DELETION_METHOD_SENTENCE: Record<string, string> = {
  format: "wiped by a disk format",
  expiry: "removed when its retention period expired",
  overwrite: "overwritten by new recordings",
  unknown: "removed by an unrecognised method",
};

export interface DeletionLike {
  method: string;
  channel: number | null;
  actor: string | null;
  action_ts_us: number | null;
  start_ts_us: number;
  end_ts_us: number;
  frames_recovered: number;
}

/**
 * One-sentence headline for a finding card, e.g. "Channel 4 was wiped by a disk format on
 * 12 Mar 2026, 15:35 IST by user admin. 300 frames (about 23 s) were recovered."
 */
export function findingHeadline(f: DeletionLike): string {
  const subject = f.channel != null ? `Channel ${f.channel}` : "This evidence image";
  const verb = DELETION_METHOD_SENTENCE[f.method] ?? DELETION_METHOD_SENTENCE.unknown;
  const when = f.action_ts_us != null ? readableMoment(f.action_ts_us) : readableMoment(f.start_ts_us);
  const byWhom = f.actor ? ` by user '${f.actor}'` : "";
  const windowSeconds = Math.max(0, (f.end_ts_us - f.start_ts_us) / 1_000_000);
  const recovered =
    f.frames_recovered > 0
      ? ` ${countWithUnit(f.frames_recovered, "frame")} (about ${formatDuration(windowSeconds)}) were recovered.`
      : "";
  return `${subject} was ${verb} on ${when}${byWhom}.${recovered}`;
}

/** "12 Mar 2026, 15:35 IST" — a date a person reads at a glance, from an epoch-microsecond field. */
export function readableMoment(tsUs: number): string {
  return readableMomentIso(new Date(tsUs / 1000).toISOString());
}

/** Same as `readableMoment` but from an ISO string field. */
export function readableMomentIso(iso: string): string {
  const full = formatTimecode(iso); // "2026-03-12 15:35:24.000 IST"
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):\d{2}(?:\.\d+)? IST$/.exec(full);
  if (!m) return full;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [, y, mo, d, h, mi] = m;
  return `${Number(d)} ${months[Number(mo) - 1]} ${y}, ${h}:${mi} IST`;
}

/**
 * Rewrite a finding's machine-generated `reasons[]` entry into a plain bullet. Reasons already
 * written in prose (the mock fixtures, and any future API text) pass through unchanged — this
 * only rewrites the specific raw shapes the real backend emits (byte offsets, `ts=<us>` log
 * correlations). The original string is never lost: callers show it verbatim in a collapsed
 * "Technical details" section alongside the plain version.
 */
export function humanizeReason(raw: string): string {
  const offsets = /^(\d+) deleted frame\(s\) recovered on channel (\d+) spanning payload offsets \d+-\d+$/.exec(raw);
  if (offsets) {
    const [, count, channel] = offsets;
    return `${countWithUnit(Number(count), "deleted frame")} were found and recovered on channel ${channel}.`;
  }

  const logCorrelation =
    /^(\S+) log event (\S+) at offset \d+ \(ts=(\d+)\) correlates with this deletion$/.exec(raw);
  if (logCorrelation) {
    const [, eventType, , tsUs] = logCorrelation;
    const eventLabel = eventType.replace(/_/g, " ");
    return `A device log entry (${eventLabel}) recorded at ${readableMoment(Number(tsUs))} matches this deletion.`;
  }

  return raw;
}

/** Short, non-technical explanation of what a finding's confidence score is based on. */
export function confidenceExplanation(reasonCount: number): string {
  if (reasonCount === 0) return "How sure we are this is a real deletion.";
  return `How sure we are this is a real deletion, based on ${countWithUnit(reasonCount, "matching signal")} (log entries and recovered data).`;
}

/** "236 KB across 300 frames" — a compact recovered-footage summary line. */
export function recoveredSummary(framesRecovered: number, bytesRecovered: number): string {
  return `${formatBytes(bytesRecovered)} across ${countWithUnit(framesRecovered, "frame")}`;
}

/** Cap a chip/id list to `max` entries, returning what to show plus the remainder count. */
export function capList<T>(items: T[], max: number): { shown: T[]; more: number } {
  if (items.length <= max) return { shown: items, more: 0 };
  return { shown: items.slice(0, max), more: items.length - max };
}

/** Plain-language source label for a coverage/frame source ("index" | "carved" | "inferred"). */
export const SOURCE_PLAIN_LABEL: Record<string, string> = {
  index: "Recorded",
  carved: "Recovered from deleted space",
  inferred: "Layout inferred",
};

/** Longer tooltip copy for the same source values — used by InfoHint next to a source badge. */
export const SOURCE_EXPLANATION: Record<string, string> = {
  index: "Found in the disk's normal recording index — the ordinary case.",
  carved: "Not in any index. Recovered by reading the raw bytes of deleted or unindexed space.",
  inferred: "The disk's layout wasn't in our known-format list, so this structure was inferred rather than read from a documented format. Treat as needing confirmation.",
};

/** Glossary of forensic/technical terms used in the UI, for InfoHint tooltips. Keep short. */
export const GLOSSARY: Record<string, string> = {
  tier: "How this evidence's file structure was understood: a known format (parsed), an inferred layout (needs confirmation), or carved by pattern-matching raw bytes.",
  "clock confidence": "How much we trust the recovered timestamps for this channel, from 0-100%. Lower confidence means the device clock may have drifted or the recording index disagreed with the on-screen clock.",
  "custody chain": "The unbroken, hash-linked record of every action taken on this case's evidence, from acquisition to export — used to prove nothing was altered.",
  "prove it": "Shows the exact bytes on disk behind this frame or finding, so a reviewer can verify it independently.",
  normalised: "Converted to one consistent time zone (IST) and clock source, so frames from different channels and devices can be compared directly.",
  carved: "Recovered by pattern-matching raw disk bytes in deleted or unindexed space — no index or file record pointed to it.",
  "layout inferred": "This disk's structure wasn't a documented format, so it was reconstructed by inference. Treat findings from it as needing confirmation.",
  osd: "On-screen display — the timestamp burned into the video image itself by the recording device, read via OCR.",
  leader: "This tile drives synced playback; the other channels follow its clock so all tiles stay in sync.",
  "deletion event": "A time window where footage was removed from the disk's normal index and had to be recovered from unindexed space.",
  "recovered footage": "Total duration of video recovered from deleted or unindexed disk space, across all deletion events.",
  channels: "The number of separate camera channels found recorded on this evidence.",
};

export { formatTimecodeUs };
