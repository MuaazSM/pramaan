-- Pramaan case database schema (docs/01-FORENSIC-CORE.md §3.2).
--
-- One database per case at <case_dir>/case.db, applied by
-- pramaan_core.db.open_case() and tracked via PRAGMA user_version. Every
-- table has a TEXT PRIMARY KEY id (audit_log additionally carries a
-- monotonic integer `seq` for chain ordering); JSON-shaped values are
-- stored as TEXT (canonical JSON per pramaan_core.ids.canonical_json where
-- the value is also content-hashed elsewhere, e.g. custody entries).
--
-- This file is a shared contract (CLAUDE.md): change it only additively —
-- new tables or new nullable/defaulted columns — and log the change under
-- "Contract changes" in the task's docs/progress/<ID>.md.

-- === migration 1: baseline schema ===

CREATE TABLE IF NOT EXISTS cases (
    id              TEXT PRIMARY KEY,
    case_number     TEXT NOT NULL,
    title           TEXT NOT NULL,
    fir_number      TEXT,
    lab             TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    created_utc     TEXT NOT NULL,
    updated_utc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS examiners (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL,              -- examiner | reviewer | admin
    pubkey_ed25519  TEXT,                        -- base64, custody signing key
    created_utc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_images (
    id              TEXT PRIMARY KEY,            -- "img_" + sha256[:16]
    case_id         TEXT NOT NULL REFERENCES cases(id),
    path            TEXT NOT NULL,
    format          TEXT NOT NULL,               -- raw | e01
    size_bytes      INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    md5             TEXT NOT NULL,
    acquired_utc    TEXT NOT NULL,
    verified        INTEGER NOT NULL DEFAULT 0,  -- 0/1
    provenance      TEXT                         -- JSON Provenance, nullable
);
CREATE INDEX IF NOT EXISTS idx_evidence_images_case ON evidence_images(case_id);

CREATE TABLE IF NOT EXISTS scan_runs (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    backend         TEXT NOT NULL,               -- rust | python
    started_utc     TEXT NOT NULL,
    finished_utc    TEXT,
    stats           TEXT,                        -- JSON
    provenance      TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_image ON scan_runs(image_id);

CREATE TABLE IF NOT EXISTS vendor_matches (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    family          TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    platform        TEXT,
    tier            TEXT NOT NULL,               -- A | B | C
    confidence      REAL NOT NULL,
    evidence        TEXT NOT NULL,               -- JSON list[str]
    model           TEXT,
    serial          TEXT,
    fs_version      TEXT
);
CREATE INDEX IF NOT EXISTS idx_vendor_matches_image ON vendor_matches(image_id);

CREATE TABLE IF NOT EXISTS recordings (
    id              TEXT PRIMARY KEY,            -- stable hash of (image_id, channel, start, offset)
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    channel         INTEGER NOT NULL,
    stream          TEXT NOT NULL,               -- main | sub
    start_ts_us     INTEGER,
    end_ts_us       INTEGER,
    byte_ranges     TEXT NOT NULL,               -- JSON list[{offset,length}]
    source          TEXT NOT NULL,               -- index | carved | inferred
    deleted         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recordings_image_channel ON recordings(image_id, channel);

CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,
    recording_id    TEXT NOT NULL REFERENCES recordings(id),
    path            TEXT NOT NULL,               -- <case_dir>/derived/clips|proxies/...
    kind            TEXT NOT NULL DEFAULT 'clip', -- clip | proxy
    sha256          TEXT NOT NULL,
    start_ts_us     INTEGER,
    end_ts_us       INTEGER,
    provenance      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_recording ON clips(recording_id);

CREATE TABLE IF NOT EXISTS deletion_findings (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    channel         INTEGER,
    start_ts_us     INTEGER NOT NULL,            -- device clock
    end_ts_us       INTEGER NOT NULL,
    method          TEXT NOT NULL,               -- format | expiry | overwrite | unknown
    actor           TEXT,
    action_ts_us    INTEGER,
    frames_recovered  INTEGER NOT NULL,
    bytes_recovered   INTEGER NOT NULL,
    confidence      REAL NOT NULL,
    reasons         TEXT NOT NULL,               -- JSON list[str]
    evidence_refs   TEXT NOT NULL                -- JSON list[str]
);
CREATE INDEX IF NOT EXISTS idx_deletion_findings_image ON deletion_findings(image_id);

CREATE TABLE IF NOT EXISTS log_events (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    ts_device_us    INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    user            TEXT,
    channel         INTEGER,
    details         TEXT NOT NULL,               -- JSON
    offset          INTEGER NOT NULL             -- where on disk the record lives
);
CREATE INDEX IF NOT EXISTS idx_log_events_image ON log_events(image_id);

CREATE TABLE IF NOT EXISTS inferred_layouts (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    header_len      INTEGER NOT NULL,
    magic           TEXT,                        -- hex
    fields          TEXT NOT NULL,               -- JSON list[InferredField]
    codec           TEXT NOT NULL,
    confirmed_by    TEXT                         -- examiner id; NULL = unconfirmed
);
CREATE INDEX IF NOT EXISTS idx_inferred_layouts_image ON inferred_layouts(image_id);

CREATE TABLE IF NOT EXISTS clock_models (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    channel         INTEGER,                     -- NULL = whole device
    segments        TEXT NOT NULL,               -- JSON list[ClockSegment]
    osd_offset_us   INTEGER,
    confidence      REAL NOT NULL,
    residual_ms     REAL NOT NULL,
    method          TEXT NOT NULL,
    overridden_by   TEXT                         -- examiner id; NULL = not overridden
);
CREATE INDEX IF NOT EXISTS idx_clock_models_image ON clock_models(image_id);

CREATE TABLE IF NOT EXISTS motion_segments (
    id              TEXT PRIMARY KEY,
    image_id        TEXT NOT NULL REFERENCES evidence_images(id),
    channel         INTEGER NOT NULL,
    start_norm_us   INTEGER NOT NULL,
    end_norm_us     INTEGER NOT NULL,
    peak_score      REAL NOT NULL,
    frames          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_motion_segments_image_channel ON motion_segments(image_id, channel);

CREATE TABLE IF NOT EXISTS detections (
    id              TEXT PRIMARY KEY,
    frame_id        TEXT NOT NULL,
    cls             TEXT NOT NULL,
    score           REAL NOT NULL,
    bbox            TEXT NOT NULL,               -- JSON [x, y, w, h], normalised
    model           TEXT NOT NULL,
    derived_from    TEXT NOT NULL                -- proxy file hash
);
CREATE INDEX IF NOT EXISTS idx_detections_frame ON detections(frame_id);

CREATE TABLE IF NOT EXISTS reports (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    report_sha256   TEXT NOT NULL,               -- canonical_json(manifest) hash
    manifest_path   TEXT NOT NULL,
    pdf_path        TEXT,
    created_utc     TEXT NOT NULL,
    created_by      TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_case ON reports(case_id);

CREATE TABLE IF NOT EXISTS exports (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    recording_id    TEXT REFERENCES recordings(id),
    path            TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    signature_path  TEXT NOT NULL,
    created_utc     TEXT NOT NULL,
    created_by      TEXT
);
CREATE INDEX IF NOT EXISTS idx_exports_case ON exports(case_id);

-- Chain-of-custody log (docs/02-BACKEND.md §8). `seq` is assigned by the
-- writer (MAX(seq) + 1 within the same transaction as the insert) so ids
-- stay content-derived (`entry_hash`) while chain order is still queryable.
CREATE TABLE IF NOT EXISTS audit_log (
    id              TEXT PRIMARY KEY,            -- = entry_hash
    seq             INTEGER NOT NULL UNIQUE,
    prev_hash       TEXT,
    entry_hash      TEXT NOT NULL,
    ts_utc          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    role            TEXT NOT NULL,
    action          TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    object_id       TEXT NOT NULL,
    payload_sha256  TEXT,
    details         TEXT NOT NULL,               -- JSON
    signature       TEXT NOT NULL                -- base64 Ed25519 signature
);
CREATE INDEX IF NOT EXISTS idx_audit_log_object ON audit_log(object_type, object_id);

CREATE TABLE IF NOT EXISTS anchors (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    backend         TEXT NOT NULL,               -- local | fabric
    merkle_root     TEXT NOT NULL,
    from_seq        INTEGER NOT NULL,
    to_seq          INTEGER NOT NULL,
    ts_utc          TEXT NOT NULL,
    lab_signature   TEXT
);
CREATE INDEX IF NOT EXISTS idx_anchors_case ON anchors(case_id);

CREATE TABLE IF NOT EXISTS llm_calls (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    feature         TEXT NOT NULL,               -- e.g. "assistant.narrative"
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    request_sha256  TEXT,
    response_sha256 TEXT,
    accepted        INTEGER,                     -- NULL = pending, 0/1 otherwise
    created_utc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_case ON llm_calls(case_id);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL,               -- queued | running | done | failed
    stage           TEXT,
    progress_pct    REAL,
    params          TEXT NOT NULL,               -- JSON
    result          TEXT,                        -- JSON
    error           TEXT,                        -- JSON
    created_utc     TEXT NOT NULL,
    updated_utc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_case ON jobs(case_id);
