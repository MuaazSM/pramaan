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
        "[10:11:44] identify: matched hiksim (tier A, confidence 0.97)",
        "[10:19:02] index_parse: 4 channels, 60 recordings",
        "[10:41:30] carve: 214 frames recovered on channel 3",
        "[11:02:15] clips: 60 stream-copied proxies rendered",
        "[11:22:08] timeline: 4-clock model built, 1 time-change marker",
        "[11:47:51] custody: 128 audit entries chained, head 7c21e0a4… 19bd",
      ],
      stages: [
        { name: "hash_verify", status: "done", pct: 100, message: "sha256 + md5 match" },
        { name: "identify", status: "done", pct: 100, message: "hiksim, tier A" },
        { name: "index_parse", status: "done", pct: 100, message: "4 channels, 60 recordings" },
        { name: "carve", status: "done", pct: 100, message: "214 frames recovered" },
        { name: "infer", status: "skipped", pct: 0, message: "index present" },
        { name: "clips", status: "done", pct: 100, message: "60 proxies" },
        { name: "timeline", status: "done", pct: 100, message: "4-clock model" },
        { name: "custody", status: "done", pct: 100, message: "128 entries" },
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
        "[05:44:19] identify: no vendor match (tier C)",
        "[05:51:40] infer: layout inference running…",
      ],
      stages: [
        { name: "hash_verify", status: "done", pct: 100, message: "sha256 + md5 match" },
        { name: "identify", status: "done", pct: 100, message: "no vendor match" },
        { name: "index_parse", status: "skipped", pct: 0, message: "no index" },
        { name: "carve", status: "running", pct: 61, message: "sector sweep 61%" },
        { name: "infer", status: "pending", pct: 0, message: null },
        { name: "clips", status: "pending", pct: 0, message: null },
        { name: "timeline", status: "pending", pct: 0, message: null },
        { name: "custody", status: "pending", pct: 0, message: null },
      ],
    },
  ],
};

function auditEntry(
  seq: number,
  prev: string | null,
  action: string,
  actor: string,
  role: string,
  objectType: string,
  objectId: string,
): AuditEntry {
  return {
    seq,
    prev_hash: prev,
    entry_hash: `${seq.toString(16).padStart(4, "0")}f09c2b8d3e6710f4c9a2b5e8d1f0c3a6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d`,
    ts_utc: `2026-03-1${2 + Math.floor(seq / 40)}T${String(9 + (seq % 12)).padStart(2, "0")}:${String(
      (seq * 7) % 60,
    ).padStart(2, "0")}:00Z`,
    actor,
    role,
    action,
    object_type: objectType,
    object_id: objectId,
    payload_sha256: seq % 3 === 0 ? "9b2e5c8f1a4d7e0b3c6f9a2d5e8b1c47a3d6f9c2b5e8f1a4d7c0b3e6f9a2d5b8" : null,
    details: {},
    signature: `sig_${seq}_demo`,
  };
}

export const AUDIT_BY_CASE: Record<string, AuditEntry[]> = {
  [DEMO_CASE.id]: (() => {
    const actions = [
      ["case.created", "examiner", "R. Deshmukh".split(" ")[0], "case", DEMO_CASE.id],
      ["evidence.registered", "examiner", "examiner", "evidence", "ev_hiksim01"],
      ["evidence.verified", "examiner", "examiner", "evidence", "ev_hiksim01"],
      ["job.scan.started", "examiner", "examiner", "job", "job_scan01"],
      ["job.scan.completed", "examiner", "examiner", "job", "job_scan01"],
      ["deletion.finding.recorded", "system", "system", "finding", "find_format01"],
      ["evidence.registered", "examiner", "examiner", "evidence", "ev_gensim02"],
      ["job.scan.started", "examiner", "examiner", "job", "job_scan02"],
    ] as const;
    const out: AuditEntry[] = [];
    let prev: string | null = null;
    for (let i = 0; i < 128; i++) {
      const [action, role, actor, objType, objId] = actions[i % actions.length];
      const e = auditEntry(i + 1, prev, action, actor, role, objType, objId);
      prev = e.entry_hash;
      out.push(e);
    }
    return out;
  })(),
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
      display_name: "Hikvision-compatible DVR (simulated)",
      platform: "HikSim-4CH",
      tier: "A",
      confidence: 0.97,
      evidence: ["index signature at LBA 63", "channel table magic 0x4849 4B56", "4 channel descriptors, 60 recordings indexed"],
      model: "DS-7204HH-K1 (sold as: Hikvision, Prama, Dahua-rebrand)",
      serial: "HS4CH-20260118-0042",
      fs_version: "hiksim-fs v3",
    },
  ],
  ev_gensim02: [
    {
      family: "gensim",
      display_name: "Unrecognised vendor (generic simulator)",
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
        source: deleted ? "carved" : "index",
        deleted,
        start_ts_us: (startHour * 3600 + ch) * 1_000_000,
        end_ts_us: ((startHour + 4) * 3600 + ch) * 1_000_000,
        byte_ranges: [{ offset: id * 4_000_000_000, length: 4_000_000_000 }],
      });
    }
  }
  return out;
}

export const RECORDINGS_BY_CASE: Record<string, Recording[]> = {
  [DEMO_CASE.id]: makeRecordings(),
};

export const DELETIONS_BY_CASE: Record<string, DeletionFinding[]> = {
  [DEMO_CASE.id]: [
    {
      id: "find_format01",
      image_id: "ev_hiksim01",
      method: "format",
      channel: 3,
      start_ts_us: 20 * 3600 * 1_000_000,
      end_ts_us: 33 * 3600 * 1_000_000,
      action_ts_us: 20 * 3600 * 1_000_000,
      actor: "admin",
      confidence: 0.91,
      frames_recovered: 214,
      bytes_recovered: 3_650_000_000,
      reasons: [
        "hdd_format log event at 2026-03-10T20:00 device clock, actor admin",
        "213 recordings missing from the index inside the format window",
        "carved frames recovered from unindexed space match channel 3 GOP structure",
      ],
      evidence_refs: ["log_hdd_format_001", "rec_031", "rec_032"],
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
      { from_device_us: null, to_device_us: 7200 * 1_000_000, offset_us: 312_000 },
      { from_device_us: 7200 * 1_000_000, to_device_us: null, offset_us: -3_600_000_000 },
    ],
  })),
};

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
