"""Motion triage: the ``motion`` pipeline stage (docs/02-BACKEND.md §6, stage
11; docs/03-AI-TIMELINE.md §6).

Per this task's brief, triage is **frame-difference based on decoded
frames** (numpy/PIL — no torch), not the payload-size heuristic sketched in
docs/03-AI-TIMELINE.md §6 ("uses only the frame index ... no decoding"); see
docs/progress/A2.md "Decisions" for why. Frames are decoded to small
grayscale derived proxies via ffmpeg (never re-encoding or modifying the
evidence image itself — CLAUDE.md rule 1/3), one decodable run at a time
(one whole live recording, or one keyframe-anchored carved run — see
``_carved_decode_runs``) so decode order matches display order.

Segmenting still follows docs §6's stated algorithm shape: a robust
(median/MAD) z-score over a rolling window, frames with score > 3 grouped
into runs of >= 1s, merged across gaps < 2s.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pramaan_core.db import open_case
from pramaan_core.evidence import EvidenceReader
from pramaan_core.frames import index_path
from pramaan_core.ids import content_id
from pramaan_core.models import MotionSegment
from pramaan_worker.runner import StageContext, StageResult

#: Downscaled decode target (docs §6 doesn't specify a size; small and
#: fixed keeps ffmpeg decode + numpy diffing fast and deterministic).
_DECODE_WIDTH = 64
_DECODE_HEIGHT = 36
_DECODE_TIMEOUT_S = 60
#: docs §6: "rolling median (window 10 s)".
_ROLLING_WINDOW_S = 10.0
#: docs §6 suggests "score > 3"; lowered here because the *real*
#: signal/noise separation this task found comes from
#: ``_MIN_ABS_DIFF_SCORE`` (below), not the z-score itself — a short,
#: truncated carved run (see ``_carved_decode_runs``) can have too few
#: samples for a 10s rolling window to isolate a brief motion blip as
#: cleanly as it would in a full-length recording, pulling otherwise-clear
#: motion frames' z down toward (not past) 3. See docs/progress/A2.md
#: "Decisions".
_Z_SCORE_THRESHOLD = 1.5
#: docs §6: "for >= 1s, merged if gaps < 2s".
_MIN_SEGMENT_DURATION_US = 1_000_000
_MERGE_GAP_US = 2_000_000
_FALLBACK_FPS = 12.5
#: Minimum raw mean-abs-diff (0-255 grayscale scale) to ever call a frame
#: "motion", regardless of z-score — see ``_segments_for_group``'s comment.
#: An engineering constant tuned against this corpus's own encoding (real
#: motion events measured ~0.15-0.55; GOP-boundary re-quantisation noise
#: measured ~0.01-0.03 — docs/progress/A2.md "Decisions"), not a physical
#: constant; revisit against real footage's own noise floor.
_MIN_ABS_DIFF_SCORE = 0.05
#: Carved (recording_id-less) frames are split into decodable runs on any
#: device-time gap bigger than this (matching the same 2s "run" convention
#: `pramaan_recovery.clip.DEFAULT_MAX_GAP_US` uses for the same purpose —
#: not imported directly, to keep this package's own dependency footprint
#: small; see docs/progress/A2.md "Decisions").
_CARVED_RUN_GAP_US = 2_000_000

#: Frame types that actually decode to a picture ffmpeg can score. Every
#: other type this pipeline indexes (``SPS``/``PPS``/``VPS``/``SEI``,
#: ``"other"``) carries no image of its own — HWSIM headers every NAL
#: individually (FIX-5: one ``FrameRef`` per physical NAL, unlike HIKSIM/
#: DHSIM's one-``FrameRef``-per-access-unit convention, whose slice payload
#: already has its access unit's SPS/PPS bundled inside it) — but a slice
#: NAL still can't be decoded on its own without the parameter sets that
#: precede it in the elementary stream. See ``_build_decode_groups``/
#: ``_decode_gray_sequence``.
_SLICE_FRAME_TYPES = ("I", "P")
#: Non-picture NAL types kept in a decode group's *byte stream* (so ffmpeg
#: has the SPS/PPS/SEI it needs) but never scored/timestamped as a motion
#: sample themselves.
_PARAM_SET_FRAME_TYPES = ("SPS", "PPS", "VPS", "SEI")
_DECODABLE_FRAME_TYPES = _SLICE_FRAME_TYPES + _PARAM_SET_FRAME_TYPES


def _skip(stage: str, ctx: StageContext, reason: str) -> StageResult:
    return StageResult(
        stage=stage,
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=None,
        message=f"{stage}: skipped ({reason})",
        skipped=True,
    )


def _decode_gray_sequence(reader: EvidenceReader, rows: list[dict[str, Any]]) -> np.ndarray | None:
    """Decode one recording's frames (in file order — the corpus/parser
    order the rest of the pipeline already treats as display order, e.g.
    docs/progress/C2.md's channel-assignment note) to a small grayscale
    ``(n, H, W)`` array via a single ffmpeg subprocess call.
    """
    payload = b"".join(reader.read(r["payload_offset"], r["payload_len"]) for r in rows)
    if not payload:
        return None
    with tempfile.TemporaryDirectory() as td:
        h264_path = Path(td) / "seg.h264"
        h264_path.write_bytes(payload)
        cmd = [
            "ffmpeg", "-y", "-f", "h264", "-i", str(h264_path),
            # One output frame per input access unit, no CFR duplication —
            # a raw elementary stream carries no reliable timing, and the
            # default fps-guessing/duplication would desync the decoded
            # array from ``rows`` (see docs/progress/A2.md "Decisions").
            "-fps_mode", "passthrough",
            "-vf", f"scale={_DECODE_WIDTH}:{_DECODE_HEIGHT},format=gray",
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ]
        try:
            proc = subprocess.run(
                cmd, check=True, capture_output=True, timeout=_DECODE_TIMEOUT_S
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None
    frame_bytes = _DECODE_WIDTH * _DECODE_HEIGHT
    raw = proc.stdout
    n = len(raw) // frame_bytes
    if n == 0:
        return None
    arr = np.frombuffer(raw[: n * frame_bytes], dtype=np.uint8)
    return arr.reshape(n, _DECODE_HEIGHT, _DECODE_WIDTH).astype(np.float32)


def frame_diff_scores(frames: np.ndarray) -> np.ndarray:
    """Mean absolute frame-to-frame difference, one value per frame
    (``frames`` is ``(n, H, W)``; the first frame repeats the second's
    score — there is no predecessor to diff it against)."""
    n = frames.shape[0]
    if n < 2:
        return np.zeros(n, dtype=np.float64)
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)).astype(np.float64)
    scores = np.empty(n, dtype=np.float64)
    scores[1:] = diffs
    scores[0] = diffs[0]
    return scores


def robust_zscore(values: np.ndarray, window: int) -> np.ndarray:
    """Rolling median/MAD z-score of ``values`` (docs §6: "rolling median
    ... robust z-score"). ``window`` is in samples, centred on each index.

    A window whose MAD is exactly 0 (mostly/entirely static baseline —
    common: this corpus's non-motion frames decode bit-identical after
    H.264 compression, so a short motion blip can be a small minority of
    values even within one supposedly "local" window) falls back to a
    whole-sequence **mean/std** z-score for that one frame instead of the
    (undefined) window-local median/MAD one. Median/MAD is deliberately the
    *primary* statistic (robust to a handful of outlier frames dominating a
    window — the usual reason to prefer it over mean/std at all), but its
    robustness is exactly what makes it blind to a real, sparse anomaly
    sitting in an otherwise perfectly-flat window: with >50% identical
    values the median/MAD literally cannot move. Mean/std has no such blind
    spot and is only reached as a fallback, never the first choice. If the
    whole sequence has zero variation too (a genuinely motion-free
    recording), std is 0 and the frame stays at z=0 — no detection, not a
    division error.
    """
    n = len(values)
    window = max(3, window)
    half = window // 2
    global_mean = float(np.mean(values)) if n else 0.0
    global_std = float(np.std(values)) if n else 0.0

    z = np.zeros(n, dtype=np.float64)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        segment = values[lo:hi]
        median = float(np.median(segment))
        mad = float(np.median(np.abs(segment - median)))
        denom = 1.4826 * mad
        if denom == 0:
            z[i] = 0.0 if global_std == 0 else (values[i] - global_mean) / global_std
        else:
            z[i] = (values[i] - median) / denom
    return z


def _estimate_window_frames(timestamps_us: list[int | None]) -> int:
    known = [t for t in timestamps_us if t is not None]
    deltas = [b - a for a, b in zip(known, known[1:], strict=False) if b > a]
    if deltas:
        period_us = float(np.median(deltas))
    else:
        period_us = 1_000_000.0 / _FALLBACK_FPS
    period_s = period_us / 1_000_000.0
    if period_s <= 0:
        period_s = 1.0 / _FALLBACK_FPS
    return max(3, round(_ROLLING_WINDOW_S / period_s))


def _timestamp(row: dict[str, Any]) -> int | None:
    ts = row.get("ts_norm_us")
    if ts is not None:
        return int(ts)
    ts = row.get("ts_header_us")
    return int(ts) if ts is not None else None


def _runs_from_flags(flags: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``[start, end]`` index runs (inclusive) where ``flags`` is
    ``True``."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def _segments_for_group(
    channel: int, image_id: str, rows: list[dict[str, Any]], scores: np.ndarray, z: np.ndarray
) -> list[MotionSegment]:
    timestamps = [_timestamp(r) for r in rows]
    # A z-score alone isn't enough: this corpus's own H.264 encoding has a
    # small (this task found: roughly an order of magnitude smaller than a
    # real motion event) periodic re-quantisation "flicker" at every GOP/
    # I-frame boundary, which — in an otherwise near-perfectly-static
    # recording — is itself a robust-statistic outlier (see
    # docs/progress/A2.md "Decisions"). Requiring the *raw* diff to also
    # clear a minimum absolute floor filters that out without needing a
    # motion event's magnitude to be known in advance.
    flags = (z > _Z_SCORE_THRESHOLD) & (scores >= _MIN_ABS_DIFF_SCORE)
    raw_runs = _runs_from_flags(flags)

    # Merge runs separated by a time gap < 2s (docs §6), skipping runs
    # whose frames have no resolvable timestamp at all.
    merged: list[list[int]] = []
    for lo, hi in raw_runs:
        if timestamps[lo] is None or timestamps[hi] is None:
            continue
        if merged and timestamps[merged[-1][1]] is not None:
            gap = timestamps[lo] - timestamps[merged[-1][1]]  # type: ignore[operator]
            if gap < _MERGE_GAP_US:
                merged[-1][1] = hi
                continue
        merged.append([lo, hi])

    segments: list[MotionSegment] = []
    for lo, hi in merged:
        start_us = timestamps[lo]
        end_us = timestamps[hi]
        if start_us is None or end_us is None or end_us - start_us < _MIN_SEGMENT_DURATION_US:
            continue
        peak = float(np.max(z[lo : hi + 1]))
        seg_id = content_id(
            "ms", {"image_id": image_id, "channel": channel, "start": start_us, "end": end_us}
        )
        segments.append(
            MotionSegment(
                id=seg_id,
                image_id=image_id,
                channel=channel,
                start_norm_us=start_us,
                end_norm_us=end_us,
                peak_score=peak,
                frames=hi - lo + 1,
            )
        )
    return segments


def _carved_decode_runs(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split a channel's recording-id-less (carved) frames into decodable
    runs: a fresh run starts at each device-time gap (measured on ``I``/``P``
    slice rows only) bigger than :data:`_CARVED_RUN_GAP_US`, and any leading
    access unit whose slice is ``P`` (not ``I``) before the run's first ``I``
    is dropped — an Annex-B stream can't be decoded without a keyframe to
    start from — that leading footage's own reference frame was physically
    overwritten, per docs/01-FORENSIC-CORE.md §4.7; CLAUDE.md rule 1 — never
    fabricate a frame that isn't there.

    Operates access-unit-at-a-time (not row-at-a-time): a dropped leading
    ``P`` access unit takes its own leading ``SPS``/``PPS``/``SEI`` rows
    (:data:`_PARAM_SET_FRAME_TYPES`, present as separate ``FrameRef``s only
    for HWSIM — FIX-5) down with it, and a *kept* access unit's leading
    parameter-set rows are kept too, so the run's byte stream (built by
    :func:`_decode_gray_sequence` from every row in the run, in
    ``payload_offset`` order) always has the SPS/PPS immediately before the
    slice that needs them.
    """
    ordered = sorted(rows, key=lambda r: r["payload_offset"])
    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    pending_non_slice: list[dict[str, Any]] = []
    started = False
    last_ts: int | None = None
    for row in ordered:
        if row["frame_type"] not in _SLICE_FRAME_TYPES:
            pending_non_slice.append(row)
            continue
        ts = _timestamp(row)
        if last_ts is not None and ts is not None and abs(ts - last_ts) > _CARVED_RUN_GAP_US:
            if current:
                runs.append(current)
            current = []
            started = False
        if not started:
            if row["frame_type"] != "I":
                pending_non_slice = []
                if ts is not None:
                    last_ts = ts
                continue
            started = True
        current.extend(pending_non_slice)
        pending_non_slice = []
        current.append(row)
        if ts is not None:
            last_ts = ts
    if current:
        runs.append(current)
    return runs


def _build_decode_groups(
    all_rows: list[dict[str, Any]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """``(channel, group_key) -> frames`` for every decodable run: frames
    with a ``recording_id`` (live index, grouped by it) plus carved frames
    (grouped via :func:`_carved_decode_runs`).

    Includes parameter-set rows (:data:`_PARAM_SET_FRAME_TYPES`) alongside
    slice rows — a group's rows become the ffmpeg *decode input* byte
    stream (:func:`_decode_gray_sequence`), which needs the SPS/PPS/SEI
    immediately preceding a slice to decode it at all (see FIX-5;
    ``motion_stage`` itself later restricts *scoring* to slice rows only,
    per this task's brief: "exclude non-slice frames from motion
    scoring")."""
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    carved_by_channel: dict[int, list[dict[str, Any]]] = {}
    for row in all_rows:
        channel = row["channel"]
        if channel is None or row["frame_type"] not in _DECODABLE_FRAME_TYPES:
            continue
        if row["recording_id"] is not None:
            groups.setdefault((channel, row["recording_id"]), []).append(row)
        else:
            carved_by_channel.setdefault(channel, []).append(row)

    for channel, rows in carved_by_channel.items():
        for i, run in enumerate(_carved_decode_runs(rows)):
            groups[(channel, f"carved-{i}")] = run
    return groups


def motion_stage(ctx: StageContext) -> StageResult:
    """The ``motion`` pipeline stage (docs/02-BACKEND.md §6 stage 11)."""
    path = index_path(ctx.case_dir, ctx.image_id)
    if not path.exists():
        return _skip("motion", ctx, "no frame index yet (frame_index stage hasn't run)")
    if not ctx.evidence_path:
        return _skip("motion", ctx, "no evidence_path on StageContext")

    table = pq.read_table(path)
    all_rows: list[dict[str, Any]] = table.to_pylist()
    groups = _build_decode_groups(all_rows)

    motion_scores: dict[str, float] = {}
    all_segments: list[MotionSegment] = []

    reader = EvidenceReader.open(ctx.evidence_path)
    try:
        for (channel, _recording_id), rows in sorted(groups.items(), key=lambda kv: kv[0]):
            # ``ordered`` (every row in the group, including any leading
            # SPS/PPS/SEI — see ``_build_decode_groups``) is the decode
            # *input*: a valid Annex-B byte stream needs its parameter sets
            # in front of the slice(s) that use them. Only the slice
            # (I/P) rows actually decode to a scoreable picture — ffmpeg
            # emits exactly one output frame per slice NAL, none for
            # SPS/PPS/SEI — so scoring/timestamps are matched against
            # ``scorable_rows`` alone (this task's brief: "exclude
            # non-slice frames from motion scoring"). For HIKSIM/DHSIM
            # (whose keyframe payload already bundles its SPS/PPS inline,
            # never a separate FrameRef) ``scorable_rows == ordered``, a
            # no-op.
            ordered = sorted(rows, key=lambda r: r["payload_offset"])
            scorable_rows = [r for r in ordered if r["frame_type"] in _SLICE_FRAME_TYPES]
            if not scorable_rows:
                continue
            frames = _decode_gray_sequence(reader, ordered)
            if frames is None:
                continue
            n = min(frames.shape[0], len(scorable_rows))
            frames = frames[:n]
            used_rows = scorable_rows[:n]
            scores = frame_diff_scores(frames)
            window = _estimate_window_frames([_timestamp(r) for r in used_rows])
            z = robust_zscore(scores, window)
            for row, score in zip(used_rows, z, strict=True):
                motion_scores[row["frame_id"]] = float(score)
            all_segments.extend(
                _segments_for_group(channel, ctx.image_id, used_rows, scores, z)
            )
    finally:
        reader.close()

    conn = open_case(ctx.case_dir)
    try:
        conn.execute("DELETE FROM motion_segments WHERE image_id = ?", (ctx.image_id,))
        for seg in sorted(all_segments, key=lambda s: (s.channel, s.start_norm_us, s.id)):
            conn.execute(
                "INSERT INTO motion_segments (id, image_id, channel, start_norm_us,"
                " end_norm_us, peak_score, frames) VALUES (?,?,?,?,?,?,?)",
                (
                    seg.id,
                    seg.image_id,
                    seg.channel,
                    seg.start_norm_us,
                    seg.end_norm_us,
                    seg.peak_score,
                    seg.frames,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    for row in all_rows:
        score = motion_scores.get(row["frame_id"])
        if score is not None:
            row["motion_score"] = score
    columns = {name: [row[name] for row in all_rows] for name in table.schema.names}
    pq.write_table(pa.table(columns, schema=table.schema), path)

    return StageResult(
        stage="motion",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=content_id(
            "motout", sorted((s.channel, s.start_norm_us, s.end_norm_us) for s in all_segments)
        ),
        message=f"motion: {len(all_segments)} segment(s) across {len(groups)} recording group(s)",
    )
