import { describe, expect, it } from "vitest";
import { istLocalToUs, usToIstLocal } from "./time";

describe("export form time helpers (IST wall clock)", () => {
  it("round-trips microseconds through the datetime-local string", () => {
    const us = Date.parse("2026-03-10T06:30:00.000Z") * 1000;
    expect(usToIstLocal(us)).toBe("2026-03-10T12:00:00");
    expect(istLocalToUs("2026-03-10T12:00:00")).toBe(us);
  });

  it("accepts the seconds-less form browsers emit by default", () => {
    expect(istLocalToUs("2026-03-10T12:00")).toBe(Date.parse("2026-03-10T06:30:00.000Z") * 1000);
  });

  it("returns null for empty or invalid input", () => {
    expect(istLocalToUs("")).toBeNull();
    expect(istLocalToUs("not-a-date")).toBeNull();
  });
});
