import { describe, expect, it } from "vitest";
import { shortHash, formatTimecode, parseTimecodeInput, formatBytes, formatDuration } from "./format";

describe("shortHash", () => {
  it("shortens a long hash to first8…last4", () => {
    expect(shortHash("a41f09c2b8d3e6710f4c9a2b5e8d1f0c3a6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d9e1d")).toBe(
      "a41f09c2…9e1d",
    );
  });

  it("leaves short hashes untouched", () => {
    expect(shortHash("abcd1234")).toBe("abcd1234");
  });
});

describe("formatTimecode", () => {
  it("renders a UTC ISO string as IST, mono-ready", () => {
    // 2026-03-12T08:32:37.480Z + 5:30 = 2026-03-12 14:02:37.480 IST
    expect(formatTimecode("2026-03-12T08:32:37.480Z")).toBe("2026-03-12 14:02:37.480 IST");
  });

  it("passes through unparsable input unchanged", () => {
    expect(formatTimecode("not-a-date")).toBe("not-a-date");
  });
});

describe("parseTimecodeInput", () => {
  it("parses HH:MM:SS", () => {
    expect(parseTimecodeInput("14:02:37")).toEqual({ kind: "time", hh: 14, mm: 2, ss: 37 });
  });

  it("parses a full date-time", () => {
    expect(parseTimecodeInput("2026-03-12 14:02")).toEqual({ kind: "time", hh: 14, mm: 2, ss: 0 });
  });

  it("parses a frame id prefixed with #", () => {
    expect(parseTimecodeInput("#f-88")).toEqual({ kind: "frame", id: "f-88" });
  });

  it("returns null for garbage input", () => {
    expect(parseTimecodeInput("not a timecode")).toBeNull();
  });
});

describe("formatBytes", () => {
  it("formats zero", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  it("formats gigabytes", () => {
    expect(formatBytes(2_147_483_648)).toBe("2.0 GB");
  });
});

describe("formatDuration", () => {
  it("formats sub-hour durations as minutes and seconds", () => {
    expect(formatDuration(125)).toBe("2m 05s");
  });

  it("formats hour-plus durations as hours and minutes", () => {
    expect(formatDuration(3661)).toBe("1h 01m");
  });
});
