"""Stage bodies (docs/02-BACKEND.md §6).

B1 built the job-runner machinery and stage 1 (``hash_verify``). This task
(B2) implements stages 2-9 — ``fingerprint`` through ``clips`` — against
the CORE interfaces in docs/01-FORENSIC-CORE.md §4.4-4.7
(``pramaan_formats``'s fingerprinter/``VendorParser``s,
``pramaan_recovery``'s layout inference/carver/clip builder,
``pramaan_logs``'s log parser). Those packages were still empty stubs when
this was written (task C2/C3 land them later), so every stage looks its
implementation up through ``pramaan_worker.registry`` — an import-guarded
registry that returns ``None`` when the real package/attribute isn't there
yet. A stage whose lookup misses records ``ok=True, skipped=True`` with a
"parser unavailable" message and the pipeline continues past it
(docs/PROMPTBOOK.md), rather than fabricating a forensic finding
(CLAUDE.md rule 6) or failing the whole job over a dependency that hasn't
landed.

Stages 10-11 (``timeline``, ``motion``) belong to the AI workstream (task
A2, docs/03-AI-TIMELINE.md). ``register_stage`` is the hook: call
``pramaan_worker.stages.register_stage("timeline", real_timeline_stage)``
(same for ``"motion"``) once a real implementation exists, and
``default_stages()`` will use it in place of the placeholder — no other
code needs to change.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pramaan_core.db import open_case
from pramaan_core.evidence import EvidenceReader, hash_image
from pramaan_core.frames import write_frames
from pramaan_core.hashing import hash_file
from pramaan_core.ids import content_hash, content_id
from pramaan_core.models import (
    ByteRange,
    FrameRef,
    LogEvent,
    Recording,
)
from pramaan_core.provenance import make_provenance

from pramaan_worker import registry, staging
from pramaan_worker.clips import build_clip_ffmpeg
from pramaan_worker.runner import STAGE_NAMES, Stage, StageContext, StageResult

#: Minimum confidence for a Tier-A vendor match to be treated as "the
#: device format is known" (docs/01-FORENSIC-CORE.md §4.5: "below 0.3 falls
#: through to inference, then carving"; docs/02-BACKEND.md §6: "only if no
#: Tier A match >= 0.8" gates ``infer_layout``). ``parse_index`` uses the
#: same threshold — a lower-confidence Tier-A match isn't trusted enough to
#: build a live index from either.
TIER_A_MIN_CONFIDENCE = 0.8

#: A fixed, non-wall-clock timestamp for ``Provenance.created_utc`` on
#: artefacts this module hashes indirectly (CLAUDE.md rule 5: "no
#: wall-clock values ... inside hashed artifacts"). ``created_utc`` itself
#: is excluded from `Provenance`'s own content hash (see its docstring),
#: but the *clips* table's ``provenance`` column is stored verbatim and
#: compared byte-for-byte by resumability/determinism tests, so a fixed
#: value keeps re-running the same input byte-identical end to end.
_EPOCH = "1970-01-01T00:00:00.000000Z"


def hash_verify(ctx: StageContext) -> StageResult:
    """Re-hash the evidence image and compare against the hash recorded at
    registration time (``ctx.expected_sha256``), if given.
    """
    if not ctx.evidence_path:
        raise ValueError("hash_verify requires StageContext.evidence_path")
    reader = EvidenceReader.open(ctx.evidence_path)
    try:
        sha256, _md5 = hash_image(reader)
    finally:
        reader.close()

    if ctx.expected_sha256 is not None and sha256 != ctx.expected_sha256:
        return StageResult(
            stage="hash_verify",
            ok=False,
            input_hash=ctx.input_hash,
            output_hash=sha256,
            message=(
                f"hash mismatch: expected sha256={ctx.expected_sha256}, recomputed sha256={sha256}"
            ),
        )
    return StageResult(
        stage="hash_verify",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=sha256,
        message=f"sha256={sha256} confirmed",
    )


def _skip(stage: str, ctx: StageContext, reason: str) -> StageResult:
    return StageResult(
        stage=stage,
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=None,
        message=f"{stage}: skipped ({reason})",
        skipped=True,
    )


def _best_tier_a_match(conn: sqlite3.Connection, image_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM vendor_matches WHERE image_id = ? AND tier = 'A' AND confidence >= ?"
        " ORDER BY confidence DESC, family LIMIT 1",
        (image_id, TIER_A_MIN_CONFIDENCE),
    ).fetchone()
    return row


def _require_evidence_path(ctx: StageContext, stage: str) -> str:
    if not ctx.evidence_path:
        raise ValueError(f"{stage} requires StageContext.evidence_path")
    return ctx.evidence_path


# --- stage 2: fingerprint ----------------------------------------------------


def fingerprint(ctx: StageContext) -> StageResult:
    fp = registry.get_fingerprinter()
    if fp is None:
        return _skip(
            "fingerprint", ctx, "parser unavailable (pramaan_formats.fingerprint not importable)"
        )
    reader = EvidenceReader.open(_require_evidence_path(ctx, "fingerprint"))
    try:
        matches = fp(reader)
    finally:
        reader.close()
    ranked = sorted(matches, key=lambda m: (-m.confidence, m.family))

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM vendor_matches WHERE image_id = ?", (ctx.image_id,))
        for i, m in enumerate(ranked):
            row_id = content_id("vm", {"image_id": ctx.image_id, "family": m.family, "i": i})
            conn.execute(
                "INSERT INTO vendor_matches (id, image_id, family, display_name, platform, tier,"
                " confidence, evidence, model, serial, fs_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row_id,
                    ctx.image_id,
                    m.family,
                    m.display_name,
                    m.platform,
                    m.tier,
                    m.confidence,
                    json.dumps(m.evidence, sort_keys=True),
                    m.model,
                    m.serial,
                    m.fs_version,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    output_hash = content_hash([m.model_dump() for m in ranked])
    return StageResult(
        stage="fingerprint",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=output_hash,
        message=f"fingerprint: {len(ranked)} vendor match(es)",
    )


# --- stage 3: parse_index (Tier A) ------------------------------------------


def parse_index(ctx: StageContext) -> StageResult:
    conn = open_case(ctx.case_dir)
    try:
        best = _best_tier_a_match(conn, ctx.image_id)
    finally:
        conn.close()
    if best is None:
        return _skip("parse_index", ctx, f"no Tier-A match >= {TIER_A_MIN_CONFIDENCE} confidence")
    family = best["family"]
    parser = registry.get_vendor_parser(family)
    if parser is None:
        return _skip("parse_index", ctx, f"parser unavailable for family {family!r}")

    reader = EvidenceReader.open(_require_evidence_path(ctx, "parse_index"))
    try:
        recordings = list(parser.list_recordings(reader))
        all_frames: list[FrameRef] = []
        for rec in recordings:
            all_frames.extend(parser.iter_frames(reader, rec))
    finally:
        reader.close()

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM recordings WHERE image_id = ?", (ctx.image_id,))
        for rec in sorted(recordings, key=lambda r: (r.channel, r.start_ts_us or 0, r.id)):
            conn.execute(
                "INSERT INTO recordings (id, image_id, channel, stream, start_ts_us, end_ts_us,"
                " byte_ranges, source, deleted) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rec.id,
                    rec.image_id,
                    rec.channel,
                    rec.stream,
                    rec.start_ts_us,
                    rec.end_ts_us,
                    json.dumps([br.model_dump() for br in rec.byte_ranges], sort_keys=True),
                    rec.source,
                    int(rec.deleted),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    staging.write_frame_stage(ctx.case_dir, ctx.image_id, "index", all_frames)
    output_hash = content_hash({"recordings": len(recordings), "frames": len(all_frames)})
    return StageResult(
        stage="parse_index",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=output_hash,
        message=(
            f"parse_index: {len(recordings)} recording(s), {len(all_frames)} frame(s) via {family}"
        ),
    )


# --- stage 4: infer_layout (Tier B) -----------------------------------------


def infer_layout(ctx: StageContext) -> StageResult:
    conn = open_case(ctx.case_dir)
    try:
        best = _best_tier_a_match(conn, ctx.image_id)
    finally:
        conn.close()
    if best is not None:
        return _skip("infer_layout", ctx, "Tier-A match already found; inference not needed")

    inferrer = registry.get_layout_inferrer()
    if inferrer is None:
        return _skip("infer_layout", ctx, "parser unavailable (pramaan_recovery.infer)")

    reader = EvidenceReader.open(_require_evidence_path(ctx, "infer_layout"))
    try:
        layout = inferrer(reader)
    finally:
        reader.close()

    if layout is None:
        return StageResult(
            stage="infer_layout",
            ok=True,
            input_hash=ctx.input_hash,
            output_hash=None,
            message="infer_layout: no layout could be inferred",
        )

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM inferred_layouts WHERE image_id = ?", (ctx.image_id,))
        conn.execute(
            "INSERT INTO inferred_layouts (id, image_id, header_len, magic, fields, codec,"
            " confirmed_by) VALUES (?,?,?,?,?,?,?)",
            (
                layout.id,
                layout.image_id,
                layout.header_len,
                layout.magic,
                json.dumps([f.model_dump() for f in layout.fields], sort_keys=True),
                layout.codec,
                layout.confirmed_by,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return StageResult(
        stage="infer_layout",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=content_hash(layout.model_dump()),
        message="infer_layout: layout inferred",
    )


# --- stage 5: carve -----------------------------------------------------


def carve(ctx: StageContext) -> StageResult:
    conn = open_case(ctx.case_dir)
    try:
        best = _best_tier_a_match(conn, ctx.image_id)
    finally:
        conn.close()
    family = best["family"] if best is not None else None

    carver = registry.get_carver(family)
    if carver is None:
        return _skip("carve", ctx, "parser unavailable (pramaan_recovery.carve)")

    reader = EvidenceReader.open(_require_evidence_path(ctx, "carve"))
    try:
        ranges: list[ByteRange]
        parser = registry.get_vendor_parser(family) if family is not None else None
        if parser is not None:
            ranges = list(parser.unindexed_ranges(reader))
        else:
            ranges = [ByteRange(offset=0, length=reader.size)]
        frames = list(carver(reader, ctx.image_id, ranges))
    finally:
        reader.close()

    staging.write_frame_stage(ctx.case_dir, ctx.image_id, "carved", frames)
    output_hash = content_hash({"frames": len(frames)})
    return StageResult(
        stage="carve",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=output_hash,
        message=f"carve: {len(frames)} frame(s) recovered from {len(ranges)} range(s)",
    )


# --- stage 6: frame_index (always runs — core-only, no registry lookup) ----


def frame_index(ctx: StageContext) -> StageResult:
    frames = staging.read_all_frames(ctx.case_dir, ctx.image_id)
    write_frames(ctx.case_dir, ctx.image_id, frames)
    output_hash = content_hash(sorted(f.frame_id for f in frames))
    return StageResult(
        stage="frame_index",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=output_hash,
        message=f"frame_index: {len(frames)} frame(s) written to the Parquet index",
    )


# --- stage 7: logs -----------------------------------------------------


def logs(ctx: StageContext) -> StageResult:
    parser = registry.get_log_parser()
    if parser is None:
        return _skip("logs", ctx, "parser unavailable (pramaan_logs.parse_logs)")

    conn = open_case(ctx.case_dir)
    try:
        best = _best_tier_a_match(conn, ctx.image_id)
    finally:
        conn.close()
    family = best["family"] if best is not None else "unknown"

    reader = EvidenceReader.open(_require_evidence_path(ctx, "logs"))
    try:
        events = list(parser(reader, family))
    finally:
        reader.close()

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM log_events WHERE image_id = ?", (ctx.image_id,))
        for ev in sorted(events, key=lambda e: (e.ts_device_us, e.offset, e.id)):
            conn.execute(
                "INSERT INTO log_events (id, image_id, ts_device_us, kind, user, channel, details,"
                " offset) VALUES (?,?,?,?,?,?,?,?)",
                (
                    ev.id,
                    ev.image_id,
                    ev.ts_device_us,
                    ev.kind,
                    ev.user,
                    ev.channel,
                    json.dumps(ev.details, sort_keys=True),
                    ev.offset,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return StageResult(
        stage="logs",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=content_hash([e.model_dump() for e in events]),
        message=f"logs: {len(events)} event(s) via {family}",
    )


# --- stage 8: deletion_verdict -----------------------------------------


def _row_to_recording(row: sqlite3.Row) -> Recording:
    return Recording(
        id=row["id"],
        image_id=row["image_id"],
        channel=row["channel"],
        stream=row["stream"],
        start_ts_us=row["start_ts_us"],
        end_ts_us=row["end_ts_us"],
        byte_ranges=[ByteRange(**br) for br in json.loads(row["byte_ranges"])],
        source=row["source"],
        deleted=bool(row["deleted"]),
    )


def _row_to_log_event(row: sqlite3.Row) -> LogEvent:
    return LogEvent(
        id=row["id"],
        image_id=row["image_id"],
        ts_device_us=row["ts_device_us"],
        kind=row["kind"],
        user=row["user"],
        channel=row["channel"],
        details=json.loads(row["details"]),
        offset=row["offset"],
    )


def deletion_verdict(ctx: StageContext) -> StageResult:
    analyzer = registry.get_deletion_analyzer()
    if analyzer is None:
        return _skip("deletion_verdict", ctx, "parser unavailable (pramaan_recovery.deletion)")

    conn = open_case(ctx.case_dir)
    try:
        recording_rows = conn.execute(
            "SELECT * FROM recordings WHERE image_id = ?", (ctx.image_id,)
        ).fetchall()
        log_rows = conn.execute(
            "SELECT * FROM log_events WHERE image_id = ?", (ctx.image_id,)
        ).fetchall()
    finally:
        conn.close()
    recordings = [_row_to_recording(r) for r in recording_rows]
    log_events = [_row_to_log_event(r) for r in log_rows]
    frames = staging.read_all_frames(ctx.case_dir, ctx.image_id)

    findings = list(
        analyzer(image_id=ctx.image_id, recordings=recordings, frames=frames, log_events=log_events)
    )

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM deletion_findings WHERE image_id = ?", (ctx.image_id,))
        for f in sorted(findings, key=lambda x: (x.start_ts_us, x.id)):
            conn.execute(
                "INSERT INTO deletion_findings (id, image_id, channel, start_ts_us, end_ts_us,"
                " method, actor, action_ts_us, frames_recovered, bytes_recovered, confidence,"
                " reasons, evidence_refs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f.id,
                    f.image_id,
                    f.channel,
                    f.start_ts_us,
                    f.end_ts_us,
                    f.method,
                    f.actor,
                    f.action_ts_us,
                    f.frames_recovered,
                    f.bytes_recovered,
                    f.confidence,
                    json.dumps(f.reasons, sort_keys=True),
                    json.dumps(f.evidence_refs, sort_keys=True),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return StageResult(
        stage="deletion_verdict",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=content_hash([f.model_dump() for f in findings]),
        message=f"deletion_verdict: {len(findings)} finding(s)",
    )


# --- stage 9: clips (stream-copy only — CLAUDE.md rule 3) --------------


def clips(ctx: StageContext) -> StageResult:
    conn = open_case(ctx.case_dir)
    try:
        recording_rows = conn.execute(
            "SELECT * FROM recordings WHERE image_id = ? AND deleted = 0", (ctx.image_id,)
        ).fetchall()
    finally:
        conn.close()
    if not recording_rows:
        return StageResult(
            stage="clips",
            ok=True,
            input_hash=ctx.input_hash,
            output_hash=None,
            message="clips: no live recordings to build clips for",
        )

    frames_by_recording: dict[str, list[FrameRef]] = {}
    for f in staging.read_all_frames(ctx.case_dir, ctx.image_id):
        if f.recording_id:
            frames_by_recording.setdefault(f.recording_id, []).append(f)

    builder = registry.get_clip_builder()
    clips_dir = Path(ctx.case_dir) / "derived" / "clips"
    made = 0

    conn = open_case(ctx.case_dir)
    try:
        conn.execute(
            "DELETE FROM clips WHERE recording_id IN"
            " (SELECT id FROM recordings WHERE image_id = ?)",
            (ctx.image_id,),
        )
        reader = EvidenceReader.open(_require_evidence_path(ctx, "clips"))
        try:
            for row in recording_rows:
                rec_id: str = row["id"]
                channel: int = row["channel"]
                frames = frames_by_recording.get(rec_id, [])
                if not frames:
                    continue
                if builder is not None:
                    # Real signature: pramaan_recovery.clip.build_clips
                    # (docs/progress/B2.md "Integration contract") — one
                    # call per recording's own frames groups them into
                    # gap-bounded runs and writes each as its own MP4 +
                    # provenance sidecar; usually one clip per recording.
                    for result in builder(
                        reader,
                        ctx.image_id,
                        channel,
                        frames,
                        clips_dir,
                        parent_sha256=ctx.expected_sha256,
                    ):
                        sha256, _md5 = hash_file(str(result.path))
                        conn.execute(
                            "INSERT INTO clips (id, recording_id, path, kind, sha256,"
                            " start_ts_us, end_ts_us, provenance) VALUES (?,?,?,?,?,?,?,?)",
                            (
                                result.clip_id,
                                rec_id,
                                str(result.path),
                                "clip",
                                sha256,
                                result.start_ts_us,
                                result.end_ts_us,
                                json.dumps(result.provenance.model_dump(), sort_keys=True),
                            ),
                        )
                        made += 1
                else:
                    sorted_frames = sorted(frames, key=lambda fr: fr.payload_offset)
                    out_path = clips_dir / f"{rec_id}.mp4"
                    build_clip_ffmpeg(reader, sorted_frames, out_path)
                    sha256, _md5 = hash_file(str(out_path))
                    prov = make_provenance(
                        step="pramaan_worker.clips.build_clip_ffmpeg",
                        params={"recording_id": rec_id, "frame_count": len(sorted_frames)},
                        parent_sha256=ctx.expected_sha256,
                        created_utc=_EPOCH,
                    )
                    clip_id = content_id("clip", {"recording_id": rec_id, "sha256": sha256})
                    conn.execute(
                        "INSERT INTO clips (id, recording_id, path, kind, sha256, start_ts_us,"
                        " end_ts_us, provenance) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            clip_id,
                            rec_id,
                            str(out_path),
                            "clip",
                            sha256,
                            sorted_frames[0].ts_header_us,
                            sorted_frames[-1].ts_header_us,
                            json.dumps(prov.model_dump(), sort_keys=True),
                        ),
                    )
                    made += 1
        finally:
            reader.close()
        conn.commit()
    finally:
        conn.close()
    return StageResult(
        stage="clips",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=content_hash({"clips": made}),
        message=f"clips: {made} clip(s) built",
    )


# --- stages 10-11: owned by A2 (docs/03-AI-TIMELINE.md) --------------------


def _make_placeholder(name: str) -> Stage:
    def _run(ctx: StageContext) -> StageResult:
        return StageResult(
            stage=name,
            ok=True,
            input_hash=ctx.input_hash,
            output_hash=None,
            message=f"{name}: placeholder — real implementation lands in task A2",
        )

    return _run


_STAGE_OVERRIDES: dict[str, Stage] = {}


def register_stage(name: str, fn: Stage) -> None:
    """Registration hook for a stage owned by another task. A2 calls this
    with ``name in {"timeline", "motion"}`` once a real implementation
    exists (docs/03-AI-TIMELINE.md); ``default_stages()`` then returns it
    in place of the placeholder, with no other code changing. Any stage
    name may be overridden this way, not just the two placeholders — e.g.
    a test can swap in a fake ``fingerprint``/``carve``/... directly,
    though registering a fake through ``pramaan_worker.registry`` (so the
    real stage body still runs) is usually the better fit for fast tests.
    """
    if name not in STAGE_NAMES:
        raise ValueError(f"Unknown stage name {name!r}; must be one of {STAGE_NAMES}")
    _STAGE_OVERRIDES[name] = fn


def reset_stage_overrides_for_tests() -> None:
    _STAGE_OVERRIDES.clear()


def default_stages() -> dict[str, Stage]:
    """Every stage name mapped to its implementation: stage 1
    (``hash_verify``, task B1) and stages 2-9 (this task) are real; stages
    10-11 (``timeline``, ``motion``) are placeholders unless A2 has called
    :func:`register_stage`. Callers that only want a subset (e.g.
    ``/evidence/{eid}/verify`` -> just ``hash_verify``) filter this dict by
    stage name before calling ``JobRunner.run``.
    """
    base: dict[str, Stage] = {
        "hash_verify": hash_verify,
        "fingerprint": fingerprint,
        "parse_index": parse_index,
        "infer_layout": infer_layout,
        "carve": carve,
        "frame_index": frame_index,
        "logs": logs,
        "deletion_verdict": deletion_verdict,
        "clips": clips,
        "timeline": _make_placeholder("timeline"),
        "motion": _make_placeholder("motion"),
    }
    base.update(_STAGE_OVERRIDES)
    return base
