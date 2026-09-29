/** Formatting helpers shared by tables, chips and the clock stack. Unit-tested in src/lib/format.test.ts. */

/** Shorten a hex hash to `first8…last4`, e.g. a41f09c2…9e1d. */
export function shortHash(hash: string, head = 8, tail = 4): string {
  if (hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

/** Format an IST-normalised ISO timestamp as `2026-03-12 14:02:37.480 IST` (mono display). */
export function formatTimecode(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  // Render in IST (UTC+5:30) regardless of viewer TZ, per BRAND.md §4.
  const istMs = d.getTime() + 5.5 * 60 * 60 * 1000;
  const ist = new Date(istMs);
  const y = ist.getUTCFullYear();
  const mo = pad(ist.getUTCMonth() + 1);
  const da = pad(ist.getUTCDate());
  const h = pad(ist.getUTCHours());
  const mi = pad(ist.getUTCMinutes());
  const s = pad(ist.getUTCSeconds());
  const ms = pad(ist.getUTCMilliseconds(), 3);
  return `${y}-${mo}-${da} ${h}:${mi}:${s}.${ms} IST`;
}

/** Parse a user-entered "go to timecode" value: HH:MM:SS, full date, or a bare frame id (e.g. #f-88). */
export function parseTimecodeInput(
  value: string,
): { kind: "time"; hh: number; mm: number; ss: number } | { kind: "frame"; id: string } | null {
  const trimmed = value.trim();
  if (trimmed.startsWith("#")) return { kind: "frame", id: trimmed.slice(1) };
  const timeOnly = /^(\d{1,2}):(\d{2}):(\d{2})$/.exec(trimmed);
  if (timeOnly) {
    return { kind: "time", hh: Number(timeOnly[1]), mm: Number(timeOnly[2]), ss: Number(timeOnly[3]) };
  }
  const full = /^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(trimmed);
  if (full) {
    return { kind: "time", hh: Number(full[2]), mm: Number(full[3]), ss: Number(full[4] ?? "0") };
  }
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** i;
  return `${i === 0 ? value : value.toFixed(1)} ${units[i]}`;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}
