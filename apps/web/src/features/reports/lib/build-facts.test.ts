import { describe, expect, it } from "vitest";
import { buildReportFacts } from "./build-facts";
import { summarizeManifest } from "./manifest";
import { GENERATED_REPORT, MOCK_DRAFT_SENTENCES, buildMockManifest } from "@/mocks/reports-fixtures";

// Same rule as packages/llm/pramaan_llm/validator.py's _NUMBER_RE.
const numbersIn = (text: string) => new Set((text.match(/\d[\d,]*(?:\.\d+)?/g) ?? []).map((n) => n.replace(/,/g, "")));

describe("buildReportFacts", () => {
  const manifest = buildMockManifest(GENERATED_REPORT);
  const facts = buildReportFacts(manifest, GENERATED_REPORT);

  it("assigns stable sequential ids, findings first", () => {
    expect(facts.map((f) => f.id)).toEqual(["fact_1", "fact_2", "fact_3", "fact_4"]);
    expect(facts[0].text).toContain("Deletion finding find_format01");
    expect(facts[1].text).toContain("Evidence ev_hiksim01");
  });

  it("is deterministic", () => {
    expect(buildReportFacts(manifest, GENERATED_REPORT)).toEqual(facts);
  });

  it("falls back to a record-level fact for a minimal (stub-mode) manifest", () => {
    const minimal = buildReportFacts({ report_id: GENERATED_REPORT.id, limitations: [] }, GENERATED_REPORT);
    expect(minimal).toHaveLength(1);
    expect(minimal[0].id).toBe("fact_1");
  });

  it("tolerates malformed arrays", () => {
    const odd = buildReportFacts({ deletion_findings: [1, "x", null, {}], evidence: "nope" }, GENERATED_REPORT);
    expect(odd).toHaveLength(1);
    expect(odd[0].text).toContain("Deletion finding unnamed");
  });

  it("mock draft sentences cite real facts and only use numbers from the cited fact", () => {
    const byId = new Map(facts.map((f) => [f.id, f.text]));
    for (const s of MOCK_DRAFT_SENTENCES) {
      expect(s.evidence_ids.length).toBeGreaterThan(0);
      const cited = s.evidence_ids.map((id) => byId.get(id));
      expect(cited.every((t) => typeof t === "string")).toBe(true);
      const allowed = numbersIn(cited.join(" "));
      for (const n of numbersIn(s.text)) expect(allowed.has(n)).toBe(true);
    }
  });
});

describe("summarizeManifest", () => {
  it("reads a full manifest defensively", () => {
    const s = summarizeManifest(buildMockManifest(GENERATED_REPORT), GENERATED_REPORT);
    expect(s.facts.find((f) => f.label === "Case")?.value).toContain("CR-2026-0412");
    expect(s.facts.find((f) => f.label === "Examiner")?.value).toBe("R. Deshmukh");
    expect(s.evidence.length).toBeGreaterThan(0);
    expect(s.limitations[0]).toMatch(/^Synthetic corpus/);
    expect(s.contents.map((c) => c.key)).toContain("deletion_findings");
  });

  it("reads the stub-mode shape and empty objects without throwing", () => {
    const stub = summarizeManifest(
      { report_id: "r", case_id: "c", report_sha256: "ab", examiner: "examiner", created_utc: "2026-03-18T09:30:00Z", limitations: ["x"] },
      GENERATED_REPORT,
    );
    expect(stub.limitations).toEqual(["x"]);
    expect(stub.evidence).toEqual([]);
    expect(() => summarizeManifest({}, GENERATED_REPORT)).not.toThrow();
  });
});
