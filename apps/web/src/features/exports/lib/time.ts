/**
 * Normalised-time <-> `<input type="datetime-local">` helpers for the export form.
 *
 * Normalised time is shown in IST everywhere in this app (BRAND.md §4, `formatTimecode`), so the
 * form fields are interpreted as IST wall-clock values regardless of the viewer's timezone. That
 * makes the microsecond values sent to `POST /cases/{cid}/exports` reproducible across machines
 * (rule 5, determinism) and consistent with the "Normalised (IST)" column on the recordings screen.
 */
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

/** Epoch microseconds -> `YYYY-MM-DDTHH:mm:ss` IST wall-clock string (datetime-local, step=1). */
export function usToIstLocal(us: number): string {
  const d = new Date(us / 1000 + IST_OFFSET_MS);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 19);
}

/** `YYYY-MM-DDTHH:mm[:ss]` IST wall-clock string -> epoch microseconds, or null if empty/invalid. */
export function istLocalToUs(local: string): number | null {
  if (!local) return null;
  const ms = Date.parse(`${local}Z`);
  if (Number.isNaN(ms)) return null;
  return Math.round((ms - IST_OFFSET_MS) * 1000);
}
