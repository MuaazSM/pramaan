import type { components } from "@/api/schema.gen";

export type EvidenceSearchFilter = components["schemas"]["EvidenceSearchFilter"];
export type FilterKey = keyof EvidenceSearchFilter;

/** How a chip is edited: drives which inline control the panel renders. */
export type ChipKind = "number-list" | "boolean" | "enum" | "text" | "datetime" | "number";

export interface FilterChip {
  key: FilterKey;
  /** Human label, e.g. "channels". */
  label: string;
  /** Display value, e.g. "2, 3" / "yes" / "carved". */
  value: string;
  /** Editor input value (what a text/select/datetime-local control should be pre-filled with). */
  editValue: string;
  kind: ChipKind;
  /** Allowed values for `kind: "enum"`. */
  options?: readonly string[];
}

/** Recording/frame sources the backend understands (packages/llm tools.py `source` description). */
export const SOURCE_OPTIONS = ["index", "carved", "inferred"] as const;

/** Stable display order + metadata for every `EvidenceSearchFilter` field. */
const FIELDS: readonly { key: FilterKey; label: string; kind: ChipKind }[] = [
  { key: "channels", label: "channels", kind: "number-list" },
  { key: "from_ist", label: "from (IST)", kind: "datetime" },
  { key: "to_ist", label: "to (IST)", kind: "datetime" },
  { key: "source", label: "source", kind: "enum" },
  { key: "deleted_only", label: "deleted only", kind: "boolean" },
  { key: "motion_min", label: "motion ≥", kind: "number" },
  { key: "detection_class", label: "detection class", kind: "text" },
  { key: "log_kind", label: "log kind", kind: "text" },
  { key: "text", label: "text", kind: "text" },
];

const DATETIME_LOCAL_RE = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/;

/** ISO string -> value for an `<input type="datetime-local">` (minute precision, wall-clock as written). */
export function toDatetimeLocal(iso: string): string {
  const m = DATETIME_LOCAL_RE.exec(iso);
  return m?.[1] ?? "";
}

/** `<input type="datetime-local">` value -> ISO 8601 in IST (the backend contract: "ISO 8601, IST"). */
export function fromDatetimeLocal(local: string): string {
  return `${local}:00+05:30`;
}

/** True when a field carries a value (null/undefined/empty list are "not set"). */
function isSet(v: unknown): boolean {
  if (v == null) return false;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

/** One chip per non-null field, in stable order. Pure: no I/O, no Date.now(). */
export function filterToChips(filter: EvidenceSearchFilter): FilterChip[] {
  const chips: FilterChip[] = [];
  for (const f of FIELDS) {
    const raw = filter[f.key];
    if (!isSet(raw)) continue;
    switch (f.kind) {
      case "number-list": {
        const list = (raw as number[]).join(", ");
        chips.push({ ...f, value: list, editValue: list });
        break;
      }
      case "boolean":
        chips.push({ ...f, value: raw ? "yes" : "no", editValue: raw ? "true" : "false" });
        break;
      case "datetime": {
        const iso = String(raw);
        chips.push({ ...f, value: iso.replace("T", " "), editValue: toDatetimeLocal(iso) });
        break;
      }
      case "enum":
        chips.push({ ...f, value: String(raw), editValue: String(raw), options: SOURCE_OPTIONS });
        break;
      default:
        chips.push({ ...f, value: String(raw), editValue: String(raw) });
    }
  }
  return chips;
}

export type ParseResult = { ok: true; value: EvidenceSearchFilter[FilterKey] } | { ok: false; error: string };

/** Parse an editor's raw string back into the field's typed value. */
export function parseChipInput(key: FilterKey, input: string): ParseResult {
  const field = FIELDS.find((f) => f.key === key);
  if (!field) return { ok: false, error: "Unknown filter field." };
  const trimmed = input.trim();
  switch (field.kind) {
    case "number-list": {
      const parts = trimmed.split(/[\s,]+/).filter(Boolean);
      if (parts.length === 0) return { ok: false, error: "Enter at least one channel number." };
      const nums = parts.map(Number);
      if (nums.some((n) => !Number.isInteger(n) || n < 0)) return { ok: false, error: "Channels are whole numbers, e.g. 2, 3." };
      return { ok: true, value: [...new Set(nums)].sort((a, b) => a - b) };
    }
    case "boolean":
      return { ok: true, value: trimmed === "true" };
    case "number": {
      const n = Number(trimmed);
      if (trimmed === "" || !Number.isFinite(n)) return { ok: false, error: "Enter a number." };
      return { ok: true, value: n };
    }
    case "datetime":
      if (!DATETIME_LOCAL_RE.test(trimmed)) return { ok: false, error: "Pick a date and time." };
      return { ok: true, value: fromDatetimeLocal(trimmed.slice(0, 16)) };
    case "enum":
      if (!(SOURCE_OPTIONS as readonly string[]).includes(trimmed)) return { ok: false, error: "Choose a source." };
      return { ok: true, value: trimmed };
    case "text":
      if (trimmed === "") return { ok: false, error: "Enter some text, or remove the filter." };
      return { ok: true, value: trimmed };
  }
}

/** Return a new filter with `key` edited. Invalid input leaves the filter unchanged. */
export function applyChipEdit(filter: EvidenceSearchFilter, key: FilterKey, input: string): EvidenceSearchFilter {
  const parsed = parseChipInput(key, input);
  return parsed.ok ? { ...filter, [key]: parsed.value } : filter;
}

/** Return a new filter with `key` cleared. */
export function removeChip(filter: EvidenceSearchFilter, key: FilterKey): EvidenceSearchFilter {
  return { ...filter, [key]: null };
}

/** True when the examiner's local filter differs from what the model proposed. */
export function isFilterEdited(original: EvidenceSearchFilter, current: EvidenceSearchFilter): boolean {
  const norm = (f: EvidenceSearchFilter) => JSON.stringify(FIELDS.map((x) => (isSet(f[x.key]) ? f[x.key] : null)));
  return norm(original) !== norm(current);
}

/**
 * True for the backend's "LLM feature is off" response: HTTP 404 with body
 * `{"error": {"code": "llm_disabled", ...}}` (docs/progress/A3.md "How the UI detects LLM disabled").
 */
export function isLlmDisabledError(status: number | undefined, body: unknown): boolean {
  if (status !== 404) return false;
  const code = (body as { error?: { code?: unknown } } | null | undefined)?.error?.code;
  return code === "llm_disabled";
}

/** Compact preview of an arbitrary result row: up to `max` primitive `key: value` pairs. */
export function previewRow(row: Record<string, unknown>, max = 4): { key: string; value: string }[] {
  const out: { key: string; value: string }[] = [];
  for (const [key, v] of Object.entries(row)) {
    if (out.length >= max) break;
    if (v == null) continue;
    if (typeof v === "object") continue;
    const s = String(v);
    out.push({ key, value: s.length > 40 ? `${s.slice(0, 39)}…` : s });
  }
  return out;
}
