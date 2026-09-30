import { describe, expect, it } from "vitest";
import {
  capList,
  confidenceExplanation,
  fileName,
  findingHeadline,
  humanizeReason,
  readableMoment,
  readableMomentIso,
  recoveredSummary,
} from "./humanize";

describe("fileName", () => {
  it("returns the last segment of a host path", () => {
    expect(fileName("/Users/muaazshaikh/pramaan/corpus/images/hiksim_format.img")).toBe("hiksim_format.img");
  });
  it("handles a bare file name", () => {
    expect(fileName("hiksim_format.img")).toBe("hiksim_format.img");
  });
  it("strips a trailing slash before taking the last segment", () => {
    expect(fileName("/evidence/cr20260412/")).toBe("cr20260412");
  });
});

describe("readableMomentIso / readableMoment", () => {
  it("renders a short human date from an ISO string", () => {
    expect(readableMomentIso("2026-03-12T10:05:24.000Z")).toBe("12 Mar 2026, 15:35 IST");
  });
  it("renders a short human date from epoch microseconds", () => {
    // 2026-03-12T10:05:24Z in epoch microseconds
    const tsUs = Date.parse("2026-03-12T10:05:24.000Z") * 1000;
    expect(readableMoment(tsUs)).toBe("12 Mar 2026, 15:35 IST");
  });
});

describe("findingHeadline", () => {
  it("builds a plain-language sentence from structured finding fields", () => {
    const headline = findingHeadline({
      method: "format",
      channel: 4,
      actor: "admin",
      action_ts_us: Date.parse("2026-03-12T10:05:24.000Z") * 1000,
      start_ts_us: Date.parse("2026-03-12T10:00:00.000Z") * 1000,
      end_ts_us: Date.parse("2026-03-12T10:00:23.920Z") * 1000,
      frames_recovered: 300,
    });
    expect(headline).toBe(
      "Channel 4 was wiped by a disk format on 12 Mar 2026, 15:35 IST by user 'admin'. 300 frames (about 0m 23s) were recovered.",
    );
  });

  it("omits the actor clause when none is known", () => {
    const headline = findingHeadline({
      method: "expiry",
      channel: null,
      actor: null,
      action_ts_us: null,
      start_ts_us: Date.parse("2026-03-12T10:00:00.000Z") * 1000,
      end_ts_us: Date.parse("2026-03-12T10:00:00.000Z") * 1000,
      frames_recovered: 0,
    });
    expect(headline).toContain("This evidence image was removed when its retention period expired on");
    expect(headline).not.toContain("by user");
    expect(headline.endsWith(".")).toBe(true);
  });
});

describe("humanizeReason", () => {
  it("rewrites a raw payload-offset reason", () => {
    expect(humanizeReason("300 deleted frame(s) recovered on channel 4 spanning payload offsets 416496-1067450")).toBe(
      "300 deleted frames were found and recovered on channel 4.",
    );
  });

  it("rewrites a raw log-correlation reason", () => {
    const result = humanizeReason(
      "hdd_format log event log_7273361ec36037f1 at offset 1067564 (ts=1773309924000000) correlates with this deletion",
    );
    expect(result).toContain("A device log entry (hdd format) recorded at");
    expect(result).toContain("matches this deletion.");
  });

  it("passes already-readable prose through unchanged", () => {
    const prose = "213 recordings missing from the index inside the format window";
    expect(humanizeReason(prose)).toBe(prose);
  });
});

describe("confidenceExplanation", () => {
  it("mentions the reason count", () => {
    expect(confidenceExplanation(3)).toBe(
      "How sure we are this is a real deletion, based on 3 matching signals (log entries and recovered data).",
    );
  });
  it("handles zero reasons", () => {
    expect(confidenceExplanation(0)).toBe("How sure we are this is a real deletion.");
  });
});

describe("recoveredSummary", () => {
  it("combines bytes and frame count", () => {
    expect(recoveredSummary(300, 236_000)).toBe("230.5 KB across 300 frames");
  });
});

describe("capList", () => {
  it("returns everything when under the cap", () => {
    expect(capList([1, 2, 3], 5)).toEqual({ shown: [1, 2, 3], more: 0 });
  });
  it("caps and reports the remainder", () => {
    expect(capList([1, 2, 3, 4, 5], 3)).toEqual({ shown: [1, 2, 3], more: 2 });
  });
});
