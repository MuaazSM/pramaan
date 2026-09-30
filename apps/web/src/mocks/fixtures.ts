import type { components } from "@/api/schema.gen";

type Case = components["schemas"]["Case"];
type EvidenceImage = components["schemas"]["EvidenceImage"];
type Job = components["schemas"]["Job"];
type AuditEntry = components["schemas"]["AuditEntry"];
type Me = components["schemas"]["Me"];
type HealthStatus = components["schemas"]["HealthStatus"];
type FsEntry = components["schemas"]["FsEntry"];
type VendorMatch = components["schemas"]["VendorMatch"];
type Recording = components["schemas"]["Recording"];
type DeletionFinding = components["schemas"]["DeletionFinding"];
type ClockModel = components["schemas"]["ClockModel"];
type LogEvent = components["schemas"]["LogEvent"];
type InferredLayout = components["schemas"]["InferredLayout"];

/**
 * Device-clock epoch base for the demo case, matching
 * `apps/api/pramaan_api/fixtures/generate.py`'s `_DEVICE_BASE` (2026-03-10T00:00:00Z) so
 * `*_ts_us` values below are real, formattable epoch microseconds rather than near-1970
 * offsets. Added for F2 (recordings/findings/evidence-detail screens need to render these as
 * timecodes) — see docs/progress/F2.md "Decisions".
 */
const DEVICE_BASE_US = Date.parse("2026-03-10T00:00:00.000Z") * 1000;

/**
 * Deterministic demo dataset for mock mode, mirroring apps/api/pramaan_api/fixtures/generate.py
 * (case CR-2026-0412, 4 channels). Pure data, no Date.now()/Math.random() — matches the backend's
 * determinism rule so screenshots are byte-stable across runs.
 */

export const USERS: Record<string, { password: string; me: Me }> = {
  examiner: { password: "demo", me: { username: "examiner", role: "examiner", display_name: "R. Deshmukh" } },
  reviewer: { password: "demo", me: { username: "reviewer", role: "reviewer", display_name: "A. Kulkarni" } },
  admin: { password: "demo", me: { username: "admin", role: "admin", display_name: "S. Iyer" } },
};

export const DEMO_CASE: Case = {
  id: "case_cr20260412",
  case_number: "CR-2026-0412",
  title: "Shopfront burglary, Andheri",
  fir_reference: "FIR-0412/2026",
  lab: "Regional FSL, Mumbai",
  status: "open",
  created_utc: "2026-03-12T09:14:00Z",
  updated_utc: "2026-03-18T06:02:00Z",
};

export const CASES: Case[] = [
  DEMO_CASE,
  {
    id: "case_cr20260287",
    case_number: "CR-2026-0287",
    title: "ATM vestibule tampering, Kothrud",
    fir_reference: "FIR-0287/2026",
    lab: "Regional FSL, Pune",
    status: "closed",
    created_utc: "2026-01-22T11:02:00Z",
    updated_utc: "2026-02-04T15:40:00Z",
  },
  {
    id: "case_cr20260501",
    case_number: "CR-2026-0501",
    title: "Warehouse theft, Bhiwandi",
    fir_reference: null,
    lab: "Regional FSL, Mumbai",
    status: "open",
    created_utc: "2026-03-27T07:30:00Z",
    updated_utc: "2026-03-29T10:05:00Z",
  },
  {
    id: "case_cr20260112",
    case_number: "CR-2026-0112",
    title: "Residential society gate, Baner",
    fir_reference: "FIR-0112/2026",
    lab: "Regional FSL, Pune",
    status: "archived",
    created_utc: "2025-12-02T08:00:00Z",
    updated_utc: "2026-01-05T09:10:00Z",
  },
];

export const CHANNELS = [
  { id: "ch1", label: "CH1 Gate" },
  { id: "ch2", label: "CH2 Shopfront" },
  { id: "ch3", label: "CH3 Counter" },
  { id: "ch4", label: "CH4 Rear lane" },
];

export const EVIDENCE_BY_CASE: Record<string, EvidenceImage[]> = {
  [DEMO_CASE.id]: [
    {
      id: "ev_hiksim01",
      path: "/evidence/cr20260412/hiksim_disk01.e01",
      format: "e01",
      size_bytes: 2_147_483_648_000,
      sha256: "a41f09c2b8d3e6710f4c9a2b5e8d1f0c3a6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d",
      md5: "3f1a9c2e7b4d6810f2c5a8e1b4d7f0a3",
      acquired_utc: "2026-03-12T10:02:00Z",
      verified: true,
    },
    {
      id: "ev_gensim02",
      path: "/evidence/cr20260412/gensim_disk02.img",
      format: "raw",
      size_bytes: 1_073_741_824_000,
      sha256: "7c21e0a4f6b9c2d5e8f1a4b7c0d3e6f9a2b5c8d1e4f7a0b3c6d9e2f5a8b1c419bd",
      md5: "9b2e5c8f1a4d7e0b3c6f9a2d5e8b1c47",
      acquired_utc: "2026-03-13T14:22:00Z",
      verified: false,
    },
  ],
};

export const JOBS_BY_CASE: Record<string, Job[]> = {
  [DEMO_CASE.id]: [
    {
      id: "job_scan01",
      case_id: DEMO_CASE.id,
      evidence_id: "ev_hiksim01",
      kind: "scan",
      status: "done",
      pct: 100,
      created_utc: "2026-03-12T10:05:00Z",
      updated_utc: "2026-03-12T11:48:00Z",
      log_lines: [
        "[10:05:01] hash_verify: sha256 match, md5 match",
        "[10:11:44] fingerprint: matched hiksim (tier A, confidence 0.97)",
        "[10:19:02] parse_index: 4 channels, 60 recordings",
        "[10:41:30] carve: 214 frames recovered on channel 3",
        "[10:52:20] frame_index: 180 frames indexed",
        "[10:58:03] logs: 8 device log events parsed",
        "[11:00:47] deletion_verdict: 1 deletion finding recorded",
        "[11:02:15] clips: 60 stream-copied proxies rendered",
        "[11:22:08] timeline: 4-clock model built, 1 time-change marker",
        "[11:40:36] motion: 12 motion segments detected",
        "[11:47:51] custody: 128 audit entries chained, head 7c21e0a4… 19bd",
      ],
      // Stage names match apps/worker/pramaan_worker/runner.py's STAGE_NAMES (the canonical 11
      // stages) — kept in sync with src/mocks/ws-handlers.ts's simulated `job.progress` events so
      // a live WS update upserts an existing stage instead of appending a duplicate (see
      // docs/progress/F2.md "Decisions": this fixture previously used ad hoc stage names that
      // didn't match, which duplicated rows in the evidence-detail pipeline panel).
      stages: [
        { name: "hash_verify", status: "done", pct: 100, message: "sha256 + md5 match" },
        { name: "fingerprint", status: "done", pct: 100, message: "hiksim, tier A, confidence 0.97" },
        { name: "parse_index", status: "done", pct: 100, message: "4 channels, 60 recordings" },
        { name: "infer_layout", status: "skipped", pct: 0, message: "index present, no inference needed" },
        { name: "carve", status: "done", pct: 100, message: "214 frames recovered on channel 3" },
        { name: "frame_index", status: "done", pct: 100, message: "180 frames indexed" },
        { name: "logs", status: "done", pct: 100, message: "8 device log events parsed" },
        { name: "deletion_verdict", status: "done", pct: 100, message: "1 deletion finding recorded" },
        { name: "clips", status: "done", pct: 100, message: "60 stream-copied proxies rendered" },
        { name: "timeline", status: "done", pct: 100, message: "4-clock model built, 1 time-change marker" },
        { name: "motion", status: "done", pct: 100, message: "12 motion segments detected" },
      ],
    },
    {
      id: "job_scan02",
      case_id: DEMO_CASE.id,
      evidence_id: "ev_gensim02",
      kind: "scan",
      status: "running",
      pct: 42,
      created_utc: "2026-03-18T05:40:00Z",
      updated_utc: "2026-03-18T06:02:00Z",
      log_lines: [
        "[05:40:02] hash_verify: sha256 match, md5 match",
        "[05:44:19] fingerprint: no vendor match (tier C)",
        "[05:51:40] infer_layout: layout inference running…",
      ],
      // See job_scan01 above: stage names match the worker's canonical 11 (STAGE_NAMES).
      stages: [
        { name: "hash_verify", status: "done", pct: 100, message: "sha256 + md5 match" },
        { name: "fingerprint", status: "done", pct: 100, message: "no vendor match" },
        { name: "parse_index", status: "skipped", pct: 0, message: "no index" },
        { name: "infer_layout", status: "running", pct: 80, message: "layout inference running…" },
        { name: "carve", status: "running", pct: 61, message: "sector sweep 61%" },
        { name: "frame_index", status: "pending", pct: 0, message: null },
        { name: "logs", status: "pending", pct: 0, message: null },
        { name: "deletion_verdict", status: "pending", pct: 0, message: null },
        { name: "clips", status: "pending", pct: 0, message: null },
        { name: "timeline", status: "pending", pct: 0, message: null },
        { name: "motion", status: "pending", pct: 0, message: null },
      ],
    },
  ],
};

/**
 * Deterministic PRNG (mulberry32 — same algorithm as review-fixtures.ts's, no Math.random(),
 * per CLAUDE.md rule 5) used only to make mock hash/signature *bytes* look like real digests
 * (full-width, non-sequential) instead of a shared constant string with one digit swapped.
 */
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

/** `seed` distinct 64-char lowercase hex string ("looks like a real sha256"), deterministic. */
function fakeHex64(seed: number): string {
  const rng = mulberry32(seed);
  let out = "";
  for (let i = 0; i < 64; i++) out += Math.floor(rng() * 16).toString(16);
  return out;
}

function auditEntry(
  seq: number,
  prev: string | null,
  tsUtc: string,
  action: string,
  actor: string,
  role: string,
  objectType: string,
  objectId: string,
): AuditEntry {
  return {
    seq,
    prev_hash: prev,
    // Each entry's hash is a function of its own seq (and, honestly, nothing else — this is a
    // display fixture, not a real hash chain) so no two entries share bytes beyond coincidence,
    // instead of the old "same 60 trailing hex chars for every row" pattern that read as fake.
    entry_hash: fakeHex64(seq * 2 + 1),
    ts_utc: tsUtc,
    actor,
    role,
    action,
    object_type: objectType,
    object_id: objectId,
    payload_sha256: seq % 3 === 0 ? fakeHex64(seq * 2 + 5000) : null,
    details: {},
    signature: fakeHex64(seq * 2 + 9000).slice(0, 88),
  };
}

/**
 * Realistic, deterministic audit narrative for the demo case (F5 fix — the previous generator
 * cycled a length-8 action list forever, so `case.created` reappeared at #1/#9/#17/... and every
 * hash shared the same 60 trailing hex chars; both read as obviously fake in the custody screen's
 * audit timeline). This builds a one-time case narrative (case creation, both evidence items'
 * intake/scan/finding lifecycle, a report and an export) followed by a long tail of routine
 * examiner/system activity — logins, re-verifications, report/export views, periodic re-scans —
 * whose object ids increment per action *type* (not per row), so nothing repeats on a short,
 * visible period the way the old fixture did. Still fully deterministic: no Date.now()/Math.random.
 */
function buildAuditLog(caseId: string, total: number): AuditEntry[] {
  type Step = readonly [action: string, role: string, actor: string, objType: string, objId: string];

  const narrative: Step[] = [
    ["case.created", "examiner", "examiner", "case", caseId],
    ["evidence.registered", "examiner", "examiner", "evidence", "ev_hiksim01"],
    ["evidence.verified", "examiner", "examiner", "evidence", "ev_hiksim01"],
    ["job.scan.started", "examiner", "examiner", "job", "job_scan01"],
    ["job.log", "system", "system", "job", "job_scan01"],
    ["job.scan.completed", "examiner", "examiner", "job", "job_scan01"],
    ["deletion.finding.recorded", "system", "system", "finding", "find_format01"],
    ["evidence.registered", "examiner", "examiner", "evidence", "ev_gensim02"],
    ["job.scan.started", "examiner", "examiner", "job", "job_scan02"],
    ["job.scan.completed", "examiner", "examiner", "job", "job_scan02"],
    ["inferred_layout.proposed", "system", "system", "layout", "ilay_gensim02_01"],
    ["report.generated", "examiner", "examiner", "report", "report_001"],
    ["export.created", "examiner", "examiner", "export", "export_001"],
    ["custody.anchor.created", "examiner", "examiner", "anchor", "anchor_local_001"],
  ];

  const pad3 = (n: number) => String(n).padStart(3, "0");

  // Routine tail: small, internally-consistent activity "bursts" (a reviewer session, a fresh
  // export + its own verification, a re-scan's start/log/complete, ...) rather than one flat
  // pool of independent rows — so a paired action (login/logout, export.created/verified,
  // job.scan.started/completed) always references the *same* freshly-minted object id, and a
  // fixed-identity object (the case, the two evidence images, the one finding) is referenced by
  // its real id forever rather than being invented a new one each visit. Object ids that
  // represent a genuinely new thing (export, report, re-scan job, session) increment a counter
  // seeded past what the one-time narrative above already used.
  let sessN = 0;
  let exportN = 1;
  let reportN = 1;
  let rescanN = 0;
  const templates: (() => Step[])[] = [
    // A: reviewer opens the case, checks findings and the report, signs off.
    () => {
      const sess = `sess_${pad3(++sessN)}`;
      return [
        ["auth.login", "reviewer", "S. Kulkarni", "session", sess],
        ["timeline.viewed", "reviewer", "S. Kulkarni", "case", caseId],
        ["findings.viewed", "reviewer", "S. Kulkarni", "finding", "find_format01"],
        ["report.viewed", "reviewer", "S. Kulkarni", "report", `report_${pad3(reportN)}`],
        ["auth.logout", "reviewer", "S. Kulkarni", "session", sess],
      ];
    },
    // B: examiner re-verifies chain integrity and the Tier A image's hash.
    () => [
      ["custody.chain.verified", "examiner", "examiner", "case", caseId],
      ["evidence.verified", "examiner", "examiner", "evidence", "ev_hiksim01"],
    ],
    // C: examiner creates a fresh signed export and immediately verifies it.
    () => {
      const id = `export_${pad3(++exportN)}`;
      return [
        ["export.created", "examiner", "examiner", "export", id],
        ["export.verified", "examiner", "examiner", "export", id],
      ];
    },
    // D: periodic re-scan of the Tier A image (e.g. after a scanner update).
    () => {
      const id = `job_rescan_${pad3(++rescanN)}`;
      return [
        ["job.scan.started", "examiner", "examiner", "job", id],
        ["job.log", "system", "system", "job", id],
        ["job.scan.completed", "examiner", "examiner", "job", id],
      ];
    },
    // E: examiner adjusts the LLM budget cap in Settings.
    () => [["settings.updated", "examiner", "examiner", "settings", "llm_budget"]],
    // F: examiner generates a follow-up report revision; the reviewer reads that one.
    () => {
      const id = `report_${pad3(++reportN)}`;
      return [
        ["report.generated", "examiner", "examiner", "report", id],
        ["report.viewed", "reviewer", "S. Kulkarni", "report", id],
      ];
    },
    // G: examiner logs a short session re-verifying the second (Tier B) image.
    () => {
      const sess = `sess_${pad3(++sessN)}`;
      return [
        ["auth.login", "examiner", "examiner", "session", sess],
        ["evidence.verified", "examiner", "examiner", "evidence", "ev_gensim02"],
        ["auth.logout", "examiner", "examiner", "session", sess],
      ];
    },
  ];

  const steps: Step[] = [...narrative];
  let ti = 0;
  outer: while (steps.length < total) {
    // Stride 3 over 7 templates (coprime) so the burst *order* doesn't repeat on a short period
    // either, independent of each burst's own incrementing object ids.
    const tpl = templates[ti % templates.length]();
    ti += 3;
    for (const s of tpl) {
      steps.push(s);
      if (steps.length >= total) break outer;
    }
  }

  // Timestamps: monotonically increasing, in bursts (pipeline stages seconds apart) separated
  // by longer human-activity gaps (minutes to hours across a multi-day examination), driven by
  // the same deterministic PRNG rather than a fixed modulo that visibly wraps every 60 entries.
  const tsRng = mulberry32(42);
  let cursorUs = Date.parse("2026-03-12T09:14:00.000Z") * 1000;
  const out: AuditEntry[] = [];
  let prev: string | null = null;
  for (let i = 0; i < steps.length; i++) {
    const [action, role, actor, objType, objId] = steps[i];
    const isPipelineStep = action.startsWith("job.") || action === "deletion.finding.recorded";
    const gapS = isPipelineStep ? 2 + Math.floor(tsRng() * 8) : 90 + Math.floor(tsRng() * 5400);
    cursorUs += gapS * 1_000_000;
    const tsUtc = new Date(Math.round(cursorUs / 1000)).toISOString().replace(/\.\d+Z$/, "Z");
    const e = auditEntry(i + 1, prev, tsUtc, action, actor, role, objType, objId);
    prev = e.entry_hash;
    out.push(e);
  }
  return out;
}

export const AUDIT_BY_CASE: Record<string, AuditEntry[]> = {
  [DEMO_CASE.id]: buildAuditLog(DEMO_CASE.id, 128),
};

export const HEALTH: HealthStatus = {
  scanner_backend: "python",
  ffmpeg: true,
  pyewf: true,
  weasyprint: true,
  fabric: false,
  llm_enabled: false,
  stub_mode: true,
};

export const FINGERPRINT_BY_EVIDENCE: Record<string, VendorMatch[]> = {
  ev_hiksim01: [
    {
      family: "hiksim",
      // Honesty rule (CLAUDE.md §7 / BRAND.md §9): synthetic corpus, never claim real-vendor
      // compatibility. "HIKSIM" is the simulator family name; the OEM lineage below is a
      // documented rebrand pattern the simulator models, not a tested-compatible claim.
      display_name: "HIKSIM · synthetic, Hikvision-style layout",
      platform: "HikSim-4CH",
      tier: "A",
      confidence: 0.97,
      evidence: ["index signature at LBA 63", "channel table magic 0x4849 4B56", "4 channel descriptors, 60 recordings indexed"],
      model: "DS-7204HH-K1 layout, synthetic — modelled on Hikvision-style layout; rebrands such as Prama (synthetic)",
      serial: "HS4CH-20260118-0042",
      fs_version: "hiksim-fs v3",
    },
  ],
  ev_gensim02: [
    {
      family: "gensim",
      display_name: "GENSIM · unrecognised layout (generic simulator)",
      platform: null,
      tier: "C",
      confidence: 0.41,
      evidence: ["no known index signature", "periodic block pattern at 4 MB stride suggests a ring buffer"],
      model: null,
      serial: null,
      fs_version: null,
    },
  ],
};

/**
 * `GET /evidence/{eid}/inferred-layout` — one unconfirmed Tier B layout for the unrecognised
 * `ev_gensim02` image (mirrors W0.3's fixture narrative: "one unconfirmed Tier B layout"), keyed
 * by evidence id (the real route has no case in its path). `ev_hiksim01` has none (Tier A, parsed
 * from a known index) — its lookup is absent on purpose so the MSW handler 404s, matching what
 * the real API does for evidence with no inference run.
 */
export const INFERRED_LAYOUT_BY_EVIDENCE: Record<string, InferredLayout> = {
  ev_gensim02: {
    id: "layout_gensim02",
    image_id: "ev_gensim02",
    header_len: 32,
    magic: null,
    codec: "h264",
    confirmed_by: null,
    fields: [
      { name: "magic", offset: 0, width: 4, endian: "be", confidence: 0.52, support: 118, unit: "none" },
      { name: "channel", offset: 4, width: 1, endian: "be", confidence: 0.88, support: 302, unit: "none" },
      { name: "timestamp", offset: 8, width: 8, endian: "le", confidence: 0.94, support: 302, unit: "s" },
      { name: "length", offset: 20, width: 4, endian: "le", confidence: 0.79, support: 289, unit: "none" },
    ],
  },
};

function makeRecordings(): Recording[] {
  const out: Recording[] = [];
  let id = 0;
  for (let ch = 1; ch <= 4; ch++) {
    for (let slice = 0; slice < 15; slice++) {
      id++;
      const startHour = slice * 4;
      const deleted = startHour >= 20 && startHour < 33; // overlaps the 13h deletion window
      out.push({
        id: `rec_${String(id).padStart(3, "0")}`,
        image_id: "ev_hiksim01",
        channel: ch,
        stream: "main",
        // The 13h deletion window is carved back from unindexed space; everything else is
        // indexed. No `inferred` recordings on the Tier A image (that source only applies to
        // ev_gensim02, which has no recording index at all in this fixture set).
        source: deleted ? "carved" : "index",
        deleted,
        start_ts_us: DEVICE_BASE_US + (startHour * 3600 + ch) * 1_000_000,
        end_ts_us: DEVICE_BASE_US + ((startHour + 4) * 3600 + ch) * 1_000_000,
        byte_ranges: [{ offset: id * 4_000_000_000, length: 4_000_000_000 }],
      });
    }
  }
  return out;
}

export const RECORDINGS_BY_CASE: Record<string, Recording[]> = {
  [DEMO_CASE.id]: makeRecordings(),
};

/**
 * Deterministic frame-id sequence (xorshift32, fixed seed — no Math.random/Date.now, per
 * CLAUDE.md's determinism rule) mirroring the real API's `evidence_refs` shape: a large flat list
 * of real `frm_…` ids, not a handful of log/recording ids. Added for F7 so mock mode reproduces
 * the same "100+ raw chips" case the real-mode screenshots caught — see docs/progress/F7.md.
 */
function frameIdSeq(count: number): string[] {
  const out: string[] = [];
  let x = 0x2545f491;
  for (let i = 0; i < count; i++) {
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
    out.push(`frm_${x.toString(16).padStart(8, "0")}${i.toString(16).padStart(4, "0")}`);
  }
  return out;
}

export const DELETIONS_BY_CASE: Record<string, DeletionFinding[]> = {
  [DEMO_CASE.id]: [
    {
      id: "find_format01",
      image_id: "ev_hiksim01",
      method: "format",
      channel: 3,
      start_ts_us: DEVICE_BASE_US + 20 * 3600 * 1_000_000,
      end_ts_us: DEVICE_BASE_US + 33 * 3600 * 1_000_000,
      action_ts_us: DEVICE_BASE_US + 20 * 3600 * 1_000_000,
      actor: "admin",
      confidence: 0.91,
      frames_recovered: 214,
      bytes_recovered: 3_650_000_000,
      reasons: [
        "hdd_format log event log_hdd_format_001 at 2026-03-10 20:00 device clock, actor admin",
        "213 recordings missing from the index inside the format window",
        "carved frames recovered from unindexed space match channel 3 GOP structure",
        "214 deleted frame(s) recovered on channel 3 spanning payload offsets 416496-1067450",
      ],
      evidence_refs: frameIdSeq(52),
    },
  ],
};

export const CLOCK_MODELS_BY_CASE: Record<string, ClockModel[]> = {
  [DEMO_CASE.id]: CHANNELS.map((_ch, i) => ({
    id: `clock_ch${i + 1}`,
    image_id: "ev_hiksim01",
    channel: i + 1,
    method: "log-anchored piecewise linear",
    confidence: i === 1 ? 0.88 : 0.97,
    residual_ms: i === 1 ? 480 : 60,
    osd_offset_us: i === 1 ? 37_000_000 : 0,
    overridden_by: null,
    segments: [
      { from_device_us: null, to_device_us: DEVICE_BASE_US + 7200 * 1_000_000, offset_us: 312_000 },
      { from_device_us: DEVICE_BASE_US + 7200 * 1_000_000, to_device_us: null, offset_us: -3_600_000_000 },
    ],
  })),
};

/**
 * `GET /cases/{cid}/log-events` — device log events: one `hdd_format` (the finding above's
 * source event), one `time_change` (docs/03-AI-TIMELINE.md §4's worked example — device clock set
 * back 1h at 02:00), and a handful of routine login/playback/power events for table density.
 */
export const LOG_EVENTS_BY_CASE: Record<string, LogEvent[]> = {
  [DEMO_CASE.id]: [
    {
      id: "log_power_on_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US,
      kind: "power_on",
      user: null,
      channel: null,
      details: {},
      offset: 4096,
    },
    {
      id: "log_login_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 2 * 3600 * 1_000_000,
      kind: "login",
      user: "admin",
      channel: null,
      details: { terminal: "local" },
      offset: 5632,
    },
    {
      id: "log_time_change_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 26 * 3600 * 1_000_000 + 2 * 3600 * 1_000_000,
      kind: "time_change",
      user: "admin",
      channel: null,
      details: { old_ts_us: DEVICE_BASE_US + 30 * 3600 * 1_000_000, new_ts_us: DEVICE_BASE_US + 26 * 3600 * 1_000_000, reason: "manual clock adjustment" },
      offset: 6144,
    },
    {
      id: "log_hdd_format_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 20 * 3600 * 1_000_000,
      kind: "hdd_format",
      user: "admin",
      channel: 3,
      details: { disk: "HDD1", reason: "user_initiated" },
      offset: 8192,
    },
    {
      id: "log_playback_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 34 * 3600 * 1_000_000,
      kind: "playback",
      user: "admin",
      channel: 3,
      details: { range: "20:00-21:00" },
      offset: 9216,
    },
    {
      id: "log_config_change_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 40 * 3600 * 1_000_000,
      kind: "config_change",
      user: "admin",
      channel: null,
      details: { field: "retention_days", old: "30", new: "14" },
      offset: 10240,
    },
    {
      id: "log_export_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 48 * 3600 * 1_000_000,
      kind: "export",
      user: "examiner",
      channel: 1,
      details: { destination: "USB0" },
      offset: 11264,
    },
    {
      id: "log_logout_001",
      image_id: "ev_hiksim01",
      ts_device_us: DEVICE_BASE_US + 58 * 3600 * 1_000_000,
      kind: "logout",
      user: "admin",
      channel: null,
      details: {},
      offset: 12288,
    },
  ],
};

/** `GET /evidence/{eid}` and `POST /evidence/{eid}/scan` have no `cid` in their path — build the
 * reverse index once from `EVIDENCE_BY_CASE` for the MSW handlers to look up by evidence id alone. */
export function findEvidenceCaseId(evidenceId: string): string | null {
  for (const [cid, list] of Object.entries(EVIDENCE_BY_CASE)) {
    if (list.some((e) => e.id === evidenceId)) return cid;
  }
  return null;
}

export function findEvidence(evidenceId: string): EvidenceImage | null {
  for (const list of Object.values(EVIDENCE_BY_CASE)) {
    const found = list.find((e) => e.id === evidenceId);
    if (found) return found;
  }
  return null;
}

export const FS_TREE: Record<string, FsEntry[]> = {
  "/evidence": [
    { name: "cr20260412", path: "/evidence/cr20260412", is_dir: true, size_bytes: null, modified_utc: "2026-03-12T09:00:00Z", looks_like_image: false },
    { name: "cr20260287", path: "/evidence/cr20260287", is_dir: true, size_bytes: null, modified_utc: "2026-01-22T10:00:00Z", looks_like_image: false },
  ],
  "/evidence/cr20260412": [
    { name: "hiksim_disk01.e01", path: "/evidence/cr20260412/hiksim_disk01.e01", is_dir: false, size_bytes: 2_147_483_648_000, modified_utc: "2026-03-12T09:58:00Z", looks_like_image: true },
    { name: "gensim_disk02.img", path: "/evidence/cr20260412/gensim_disk02.img", is_dir: false, size_bytes: 1_073_741_824_000, modified_utc: "2026-03-13T14:10:00Z", looks_like_image: true },
    { name: "notes.txt", path: "/evidence/cr20260412/notes.txt", is_dir: false, size_bytes: 812, modified_utc: "2026-03-12T09:59:00Z", looks_like_image: false },
  ],
};
