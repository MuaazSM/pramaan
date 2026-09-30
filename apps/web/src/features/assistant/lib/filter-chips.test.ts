import { describe, expect, it } from "vitest";
import {
  applyChipEdit,
  filterToChips,
  isFilterEdited,
  isLlmDisabledError,
  parseChipInput,
  previewRow,
  removeChip,
} from "./filter-chips";

describe("filterToChips", () => {
  it("emits one chip per non-null field in stable order", () => {
    const chips = filterToChips({ text: "door", channels: [3, 2], deleted_only: true, source: null, to_ist: undefined });
    expect(chips.map((c) => c.key)).toEqual(["channels", "deleted_only", "text"]);
    expect(chips[0]).toMatchObject({ label: "channels", value: "3, 2", kind: "number-list" });
    expect(chips[1]).toMatchObject({ value: "yes", kind: "boolean" });
  });
  it("skips empty channel lists and keeps false booleans", () => {
    expect(filterToChips({ channels: [] })).toEqual([]);
    expect(filterToChips({ deleted_only: false })[0]?.value).toBe("no");
  });
  it("gives datetime chips a datetime-local edit value", () => {
    const [c] = filterToChips({ from_ist: "2026-03-12T14:00:00+05:30" });
    expect(c).toMatchObject({ kind: "datetime", editValue: "2026-03-12T14:00", value: "2026-03-12 14:00:00+05:30" });
  });
});

describe("editing", () => {
  it("parses and normalises channel lists", () => {
    expect(parseChipInput("channels", "3, 2 3")).toEqual({ ok: true, value: [2, 3] });
    expect(parseChipInput("channels", "x").ok).toBe(false);
  });
  it("round-trips datetimes as IST ISO strings", () => {
    expect(parseChipInput("to_ist", "2026-03-12T15:30")).toEqual({ ok: true, value: "2026-03-12T15:30:00+05:30" });
  });
  it("rejects unknown sources and leaves the filter unchanged on invalid input", () => {
    const f = { source: "carved" };
    expect(applyChipEdit(f, "source", "bogus")).toBe(f);
    expect(applyChipEdit(f, "source", "index")).toEqual({ source: "index" });
  });
  it("removes chips and detects local edits", () => {
    const orig = { channels: [2], deleted_only: true };
    expect(isFilterEdited(orig, { ...orig })).toBe(false);
    expect(isFilterEdited(orig, removeChip(orig, "deleted_only"))).toBe(true);
    expect(filterToChips(removeChip(orig, "channels")).map((c) => c.key)).toEqual(["deleted_only"]);
  });
});

describe("isLlmDisabledError", () => {
  it("matches only 404 + llm_disabled", () => {
    expect(isLlmDisabledError(404, { error: { code: "llm_disabled" } })).toBe(true);
    expect(isLlmDisabledError(404, { error: { code: "not_found" } })).toBe(false);
    expect(isLlmDisabledError(500, { error: { code: "llm_disabled" } })).toBe(false);
    expect(isLlmDisabledError(404, null)).toBe(false);
  });
});

describe("previewRow", () => {
  it("renders primitives defensively and skips nested/null values", () => {
    expect(previewRow({ a: 1, b: null, c: { x: 1 }, d: "hi", e: true }, 3)).toEqual([
      { key: "a", value: "1" },
      { key: "d", value: "hi" },
      { key: "e", value: "true" },
    ]);
  });
});
