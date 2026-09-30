"""Pipeline integration: the ``timeline`` stage (docs/02-BACKEND.md §6, stage
10; docs/03-AI-TIMELINE.md §4).

This is the one small adapter module coupling ``pramaan_timeline``'s pure
building blocks (``clock.py``, ``osd.py``, ``patterns.py`` — task A1) to the
BACKEND pipeline interfaces (``apps/worker/pramaan_worker/runner.StageContext``
/``StageResult``, ``pramaan_core.db``/``frames``) per B2's registration hook
(docs/progress/B2.md "Integration contract": ``pramaan_worker.stages
.register_stage("timeline", fn)`` where ``fn: (ctx: StageContext) ->
StageResult``).

``timeline_stage``:

1. Reads the image's seizure ``ClockObservation`` (``clock_observations``,
   ``channel IS NULL AND source = 'seizure'``) and every ``time_change``
   ``LogEvent`` (``log_events``), and reconstructs device-clock segments
   (:func:`pramaan_timeline.clock.reconstruct_segments`).
2. For every channel with recordings, samples decoded I-frame keyframes
   (derived proxies — CLAUDE.md rule 1/3: evidence bytes are only ever read,
   never written or re-encoded; the decoded image is a transient in-memory
   artefact, not written to disk), reads the on-screen time with
   :class:`pramaan_timeline.osd.OsdReader`, and computes
   ``osd_offset_us = median(osd_ts - header_ts)``.
3. Builds one :class:`~pramaan_core.models.ClockModel` per channel (plus one
   whole-device fallback, ``channel=None``, for rows whose own channel has no
   dedicated model), persists them to ``clock_models``, and fills
   ``ts_osd_us`` (sampled frames only) / ``ts_norm_us`` / ``norm_confidence``
   into the Parquet frame index in place.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image
from pramaan_core.db import open_case
from pramaan_core.evidence import EvidenceReader
from pramaan_core.frames import index_path
from pramaan_core.ids import content_id
from pramaan_core.models import ClockModel, ClockObservation, LogEvent
from pramaan_worker.runner import StageContext, StageResult

from pramaan_timeline.clock import (
    OSD_RESIDUAL_OK_THRESHOLD_S,
    build_clock_model,
    compute_confidence,
    header_index_agreement,
    normalise_frame_table,
    reconstruct_segments,
)
from pramaan_timeline.osd import (
    ASSET_FONT_PATH,
    OcrEngine,
    OsdReader,
    TemplateEngine,
    compute_osd_offset,
    default_engines,
    describe_osd_drift,
)

#: docs/03-AI-TIMELINE.md §4 step 4: "sample one decoded keyframe every 30s
#: of footage per channel". Frames are thinned to at least this many device
#: microseconds apart before OCR runs (all sampled if the channel has fewer
#: keyframes spanning less time than this).
SAMPLE_INTERVAL_US = 30_000_000
#: Upper bound on OSD samples per channel, regardless of footage length —
#: bounds ffmpeg-decode + OCR cost on a channel with many short recordings
#: (the corpus's recordings are far shorter than real footage; see
#: docs/progress/A2.md "Decisions").
MAX_SAMPLES_PER_CHANNEL = 60
_DECODE_TIMEOUT_S = 30

#: Q1's synthetic OSD font (docs/progress/Q1.md "Corpus summary":
#: "tools/synthdvr/assets/fonts/DejaVuSansMono.ttf"), used to build a
#: corpus-tuned ``TemplateEngine`` fallback. Resolved opportunistically —
#: falls back to A1's own bundled font (visually identical DejaVu Sans Mono)
#: when the monorepo's ``tools/`` tree isn't present (e.g. an installed
#: wheel without the repo checkout).
_CORPUS_FONT_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "synthdvr" / "assets" / "fonts"
    / "DejaVuSansMono.ttf"
)


def _osd_engines() -> list[OcrEngine]:
    font_path = _CORPUS_FONT_PATH if _CORPUS_FONT_PATH.exists() else ASSET_FONT_PATH
    engines = default_engines()
    # Replace the default (A1-bundled-font) TemplateEngine with one tuned to
    # the corpus's own font file, per this task's brief.
    return [e for e in engines if not isinstance(e, TemplateEngine)] + [
        TemplateEngine(font_path=font_path)
    ]


def _skip(stage: str, ctx: StageContext, reason: str) -> StageResult:
    return StageResult(
        stage=stage,
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=None,
        message=f"{stage}: skipped ({reason})",
        skipped=True,
    )


def _row_to_clock_observation(row: Any) -> ClockObservation:
    return ClockObservation(
        id=row["id"],
        image_id=row["image_id"],
        channel=row["channel"],
        source=row["source"],
        device_ts_us=row["device_ts_us"],
        reference_ts_us=row["reference_ts_us"],
        offset_us=row["offset_us"],
        weight=row["weight"],
        details=json.loads(row["details"]),
    )


def _row_to_log_event(row: Any) -> LogEvent:
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


def _decode_frame_to_image(
    reader: EvidenceReader, payload_offset: int, payload_len: int
) -> Image.Image | None:
    """Decode one access unit's own payload bytes to an RGB image.

    A *derived*, in-memory artefact only (CLAUDE.md rule 1/3): the evidence
    image is opened read-only via ``EvidenceReader``; nothing is written
    back to it, and the decode is a stream-copy-free ffmpeg still-frame
    render (not a re-encode of the original video). Mirrors the same
    single-frame decode technique task B2 already uses for
    ``GET /frames/{fid}/thumb`` (``apps/api/pramaan_api/real/pipeline_store
    .frame_thumbnail_bytes``).
    """
    payload = reader.read(payload_offset, payload_len)
    with tempfile.TemporaryDirectory() as td:
        h264_path = Path(td) / "frame.h264"
        png_path = Path(td) / "frame.png"
        h264_path.write_bytes(payload)
        cmd = [
            "ffmpeg", "-y", "-f", "h264", "-i", str(h264_path), "-frames:v", "1", str(png_path)
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=_DECODE_TIMEOUT_S)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None
        if not png_path.exists():
            return None
        image = Image.open(png_path)
        image.load()
        return image.convert("RGB")


def _sample_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick keyframes at least :data:`SAMPLE_INTERVAL_US` apart (device
    time), capped at :data:`MAX_SAMPLES_PER_CHANNEL`."""
    candidates = sorted(rows, key=lambda r: r["ts_header_us"])
    if not candidates:
        return []
    sampled = [candidates[0]]
    for row in candidates[1:]:
        if row["ts_header_us"] - sampled[-1]["ts_header_us"] >= SAMPLE_INTERVAL_US:
            sampled.append(row)
    if len(sampled) > MAX_SAMPLES_PER_CHANNEL:
        step = len(sampled) / MAX_SAMPLES_PER_CHANNEL
        sampled = [sampled[int(i * step)] for i in range(MAX_SAMPLES_PER_CHANNEL)]
    return sampled


def _osd_sample_channel(
    reader: EvidenceReader, channel_rows: list[dict[str, Any]], reader_engine: OsdReader
) -> tuple[dict[str, int], list[tuple[int, int]]]:
    """Decode + OCR sampled I-frames for one channel.

    Returns ``(ts_osd_by_frame_id, (osd_ts_us, header_ts_us) pairs)``.
    """
    keyframes = [
        r for r in channel_rows if r["frame_type"] == "I" and r["ts_header_us"] is not None
    ]
    sampled = _sample_rows(keyframes)
    ts_osd_by_frame_id: dict[str, int] = {}
    pairs: list[tuple[int, int]] = []
    images: list[Image.Image] = []
    decoded_rows: list[dict[str, Any]] = []
    for row in sampled:
        image = _decode_frame_to_image(reader, row["payload_offset"], row["payload_len"])
        if image is None:
            continue
        images.append(image)
        decoded_rows.append(row)
    if not images:
        return ts_osd_by_frame_id, pairs

    results = reader_engine.read_sequence(images)
    for row, result in zip(decoded_rows, results, strict=True):
        if result.reading is None:
            continue
        osd_ts = result.reading.device_ts_us
        ts_osd_by_frame_id[row["frame_id"]] = osd_ts
        pairs.append((osd_ts, row["ts_header_us"]))
    return ts_osd_by_frame_id, pairs


def _channel_header_index_agreement(
    conn: Any, image_id: str, channel: int, rows_by_channel: dict[int, list[dict[str, Any]]]
) -> bool:
    recs = conn.execute(
        "SELECT * FROM recordings WHERE image_id = ? AND channel = ? AND source = 'index'",
        (image_id, channel),
    ).fetchall()
    if not recs:
        return True
    frames = rows_by_channel.get(channel, [])
    agree = True
    for rec in recs:
        rec_id = rec["id"]
        headers = [
            f["ts_header_us"]
            for f in frames
            if f["recording_id"] == rec_id and f["ts_header_us"] is not None
        ]
        if not headers:
            continue
        result = header_index_agreement(
            min(headers), max(headers), rec["start_ts_us"], rec["end_ts_us"]
        )
        if not result.agree:
            agree = False
    return agree


def timeline_stage(ctx: StageContext) -> StageResult:
    """The ``timeline`` pipeline stage (docs/02-BACKEND.md §6 stage 10)."""
    path = index_path(ctx.case_dir, ctx.image_id)
    if not path.exists():
        return _skip("timeline", ctx, "no frame index yet (frame_index stage hasn't run)")

    conn = open_case(ctx.case_dir)
    try:
        seizure_row = conn.execute(
            "SELECT * FROM clock_observations WHERE image_id = ? AND channel IS NULL"
            " AND source = 'seizure' ORDER BY id LIMIT 1",
            (ctx.image_id,),
        ).fetchone()
        time_change_rows = conn.execute(
            "SELECT * FROM log_events WHERE image_id = ? AND kind = 'time_change'"
            " ORDER BY ts_device_us",
            (ctx.image_id,),
        ).fetchall()
        channel_rows = conn.execute(
            "SELECT DISTINCT channel FROM recordings WHERE image_id = ? ORDER BY channel",
            (ctx.image_id,),
        ).fetchall()
    finally:
        conn.close()

    if seizure_row is None:
        return _skip("timeline", ctx, "no seizure ClockObservation for this image")

    seizure = _row_to_clock_observation(seizure_row)
    time_changes = [_row_to_log_event(r) for r in time_change_rows]
    segments = reconstruct_segments(seizure, time_changes)

    table = pq.read_table(path)
    all_rows: list[dict[str, Any]] = table.to_pylist()
    channels = sorted({r["channel"] for r in channel_rows}) or sorted(
        {r["channel"] for r in all_rows if r["channel"] is not None}
    )

    rows_by_channel: dict[int, list[dict[str, Any]]] = {}
    for row in all_rows:
        if row["channel"] is not None:
            rows_by_channel.setdefault(row["channel"], []).append(row)

    ts_osd_updates: dict[str, int] = {}
    clock_models: dict[int | None, ClockModel] = {}
    overall_agree = True
    evidence_path = ctx.evidence_path

    if evidence_path is not None and channels:
        engines = _osd_engines()
        reader = EvidenceReader.open(evidence_path)
        try:
            conn = open_case(ctx.case_dir)
            try:
                for channel in channels:
                    channel_rows_list = rows_by_channel.get(channel, [])
                    header_index_agree = _channel_header_index_agreement(
                        conn, ctx.image_id, channel, rows_by_channel
                    )
                    overall_agree = overall_agree and header_index_agree

                    osd_reader = OsdReader(engines=engines)
                    ts_osd_by_frame, pairs = _osd_sample_channel(
                        reader, channel_rows_list, osd_reader
                    )
                    ts_osd_updates.update(ts_osd_by_frame)

                    osd_offset_us, residual_ms = (
                        compute_osd_offset(pairs) if pairs else (None, 0.0)
                    )
                    residual_s = residual_ms / 1000.0
                    osd_residual_ok = (
                        osd_offset_us is not None and residual_s < OSD_RESIDUAL_OK_THRESHOLD_S
                    )
                    confidence = compute_confidence(
                        has_seizure_anchor=True,
                        header_index_agree=header_index_agree,
                        osd_residual_ok=osd_residual_ok,
                    )
                    drift_sentence = (
                        describe_osd_drift(osd_offset_us, channel)
                        if osd_offset_us is not None
                        else None
                    )
                    seizure_s = seizure.offset_us / 1_000_000
                    method_parts = [f"Seizure offset {seizure_s:+.1f}s at intake"]
                    if len(segments) > 1:
                        n_changes = len(segments) - 1
                        method_parts.append(f"{n_changes} clock-change segment(s) reconstructed")
                    if drift_sentence:
                        method_parts.append(drift_sentence)
                    elif osd_offset_us is not None:
                        n = len(pairs)
                        method_parts.append(f"OSD agrees with device clock ({n} sample(s))")
                    else:
                        method_parts.append("no OSD reading available")

                    model_id = content_id(
                        "cm", {"image_id": ctx.image_id, "channel": channel, "v": ctx.input_hash}
                    )
                    clock_models[channel] = build_clock_model(
                        id=model_id,
                        image_id=ctx.image_id,
                        channel=channel,
                        segments=segments,
                        osd_offset_us=osd_offset_us,
                        confidence=confidence,
                        residual_ms=residual_ms,
                        method="; ".join(method_parts) + ".",
                    )
            finally:
                conn.close()
        finally:
            reader.close()

    # Whole-device fallback model, for any row whose channel has no
    # dedicated model above (e.g. Tier C/no-recordings images).
    device_confidence = compute_confidence(
        has_seizure_anchor=True, header_index_agree=overall_agree, osd_residual_ok=False
    )
    device_seizure_s = seizure.offset_us / 1_000_000
    clock_models[None] = build_clock_model(
        id=content_id("cm", {"image_id": ctx.image_id, "channel": None, "v": ctx.input_hash}),
        image_id=ctx.image_id,
        channel=None,
        segments=segments,
        osd_offset_us=None,
        confidence=device_confidence,
        residual_ms=0.0,
        method=f"Device-wide: seizure offset {device_seizure_s:+.1f}s, no per-channel OSD.",
    )

    def _channel_sort_key(model: ClockModel) -> int:
        return model.channel if model.channel is not None else -1

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM clock_models WHERE image_id = ?", (ctx.image_id,))
        for model in sorted(clock_models.values(), key=_channel_sort_key):
            conn.execute(
                "INSERT INTO clock_models (id, image_id, channel, segments, osd_offset_us,"
                " confidence, residual_ms, method, overridden_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    model.id,
                    model.image_id,
                    model.channel,
                    json.dumps([s.model_dump() for s in model.segments], sort_keys=True),
                    model.osd_offset_us,
                    model.confidence,
                    model.residual_ms,
                    model.method,
                    model.overridden_by,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    for row in all_rows:
        osd_ts = ts_osd_updates.get(row["frame_id"])
        if osd_ts is not None:
            row["ts_osd_us"] = osd_ts

    columns = {name: [row[name] for row in all_rows] for name in table.schema.names}
    updated_table = pa.table(columns, schema=table.schema)
    normalised = normalise_frame_table(updated_table, clock_models)
    pq.write_table(normalised, path)

    output_summary = {
        str(channel): {"confidence": model.confidence, "osd_offset_us": model.osd_offset_us}
        for channel, model in sorted(clock_models.items(), key=lambda kv: str(kv[0]))
    }
    return StageResult(
        stage="timeline",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=content_id("tlout", output_summary),
        message=(
            f"timeline: {len([c for c in clock_models if c is not None])} channel clock model(s), "
            f"{len(ts_osd_updates)} OSD sample(s)"
        ),
    )
