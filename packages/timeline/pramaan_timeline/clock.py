"""Four-clock normalisation: clock segment reconstruction, header/index
agreement scoring, the confidence formula, and the frame-table normalisation
function (docs/03-AI-TIMELINE.md §4).

All device timestamps in this module are integer **microseconds since the
Unix epoch, computed in UTC** (``datetime(..., tzinfo=timezone.utc)``), never
the host's local timezone — this keeps segment reconstruction and
normalisation deterministic regardless of which machine runs the code
(CLAUDE.md rule 5). "True"/"reference" time uses the same convention;
display-in-IST (docs §4 step 5) is a presentation concern for the API/web
layer, not this module.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import pyarrow as pa
from pramaan_core.models import ClockModel, ClockObservation, ClockSegment, LogEvent

#: docs/03-AI-TIMELINE.md §4 step 3: header vs index start/end disagreement
#: beyond this many seconds lowers confidence and is recorded as a reason.
HEADER_INDEX_DISAGREEMENT_THRESHOLD_S = 2.0

#: docs/03-AI-TIMELINE.md §4 step 4: |osd_offset| beyond this is worth
#: recording as a named drift (e.g. "camera OSD differs ... by +37.0 s").
OSD_DRIFT_NOTEWORTHY_THRESHOLD_S = 1.0

#: docs/03-AI-TIMELINE.md §4 step 6: OSD residual under this is "agreement".
OSD_RESIDUAL_OK_THRESHOLD_S = 1.0

#: An "unexplained jump" for the confidence formula: a discontinuity between
#: consecutive normalised timestamps bigger than this with no segment
#: boundary or OSD-offset change to explain it.
UNEXPLAINED_JUMP_THRESHOLD_S = 5.0


# --------------------------------------------------------------------------
# Segment reconstruction (docs §4 steps 1-2)
# --------------------------------------------------------------------------


def reconstruct_segments(
    seizure: ClockObservation, time_changes: Sequence[LogEvent] = ()
) -> list[ClockSegment]:
    """Reconstruct piecewise-constant device-clock offset segments.

    ``seizure`` is a :class:`ClockObservation` with ``source="seizure"``:
    ``device_ts_us`` is the DVR-displayed time at intake, ``offset_us`` is
    ``dvr_displayed - reference`` (device minus true; positive = device
    ahead) already computed by the caller (intake form). It applies to the
    most recent (open-ended) segment.

    ``time_changes`` are ``LogEvent``s with ``kind="time_change"``, each
    recording a jump in the device's *displayed* clock at device time
    ``ts_device_us`` (the display value immediately before the jump —
    ``details["old_ts_us"]``) to ``details["new_ts_us"]``. Walking backwards
    from the seizure segment, each earlier segment's offset is
    ``offset_before = offset_after - (new_ts_us - old_ts_us)`` (docs §4
    step 2) — true time is continuous across the jump even though the
    device's displayed value is not.

    Returns segments sorted oldest-first, each ``ClockSegment`` covering
    ``[from_device_us, to_device_us)`` in *displayed device* time (``None``
    means unbounded on that side).
    """
    if seizure.source != "seizure":
        msg = f"reconstruct_segments requires a seizure observation, got {seizure.source!r}"
        raise ValueError(msg)

    changes = sorted(_time_change_jumps(time_changes), key=lambda c: c.old_ts_us)
    for a, b in zip(changes, changes[1:], strict=False):
        if a.old_ts_us >= b.old_ts_us or a.new_ts_us >= b.new_ts_us:
            msg = "time_change events must be non-overlapping and chronologically ordered"
            raise ValueError(msg)

    segments: list[ClockSegment] = []
    offset_after = seizure.offset_us
    upper: int | None = None
    lower = changes[-1].new_ts_us if changes else None
    segments.append(ClockSegment(from_device_us=lower, to_device_us=upper, offset_us=offset_after))

    for i in range(len(changes) - 1, -1, -1):
        change = changes[i]
        offset_before = offset_after - (change.new_ts_us - change.old_ts_us)
        upper = change.old_ts_us
        lower = changes[i - 1].new_ts_us if i > 0 else None
        segments.append(
            ClockSegment(from_device_us=lower, to_device_us=upper, offset_us=offset_before)
        )
        offset_after = offset_before

    segments.reverse()
    return segments


@dataclass(frozen=True, slots=True)
class _TimeChangeJump:
    old_ts_us: int
    new_ts_us: int


def _time_change_jumps(events: Iterable[LogEvent]) -> list[_TimeChangeJump]:
    jumps: list[_TimeChangeJump] = []
    for event in events:
        if event.kind != "time_change":
            continue
        old_ts = event.details.get("old_ts_us")
        new_ts = event.details.get("new_ts_us")
        if not isinstance(old_ts, int) or not isinstance(new_ts, int):
            raise ValueError(
                f"time_change LogEvent {event.id!r} is missing integer "
                "details['old_ts_us']/details['new_ts_us']"
            )
        jumps.append(_TimeChangeJump(old_ts_us=old_ts, new_ts_us=new_ts))
    return jumps


def offset_for_device_ts(segments: Sequence[ClockSegment], device_ts_us: int) -> int:
    """Return the ``offset_us`` of the segment covering ``device_ts_us``.

    Segments must be sorted oldest-first (as returned by
    :func:`reconstruct_segments`) and are treated as contiguous, half-open
    ``[from_device_us, to_device_us)`` ranges. Falls back to the nearest
    segment if ``device_ts_us`` falls outside all of them (e.g. a frame
    slightly before the earliest known boundary).
    """
    if not segments:
        raise ValueError("no segments to look up an offset in")
    for seg in segments:
        lo = seg.from_device_us if seg.from_device_us is not None else -math.inf
        hi = seg.to_device_us if seg.to_device_us is not None else math.inf
        if lo <= device_ts_us < hi:
            return seg.offset_us
    first, last = segments[0], segments[-1]
    if first.from_device_us is not None and device_ts_us < first.from_device_us:
        return first.offset_us
    return last.offset_us


# --------------------------------------------------------------------------
# Header vs index agreement (docs §4 step 3)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgreementResult:
    agree: bool
    max_diff_s: float
    reason: str | None


def header_index_agreement(
    header_start_us: int | None,
    header_end_us: int | None,
    index_start_us: int | None,
    index_end_us: int | None,
    *,
    threshold_s: float = HEADER_INDEX_DISAGREEMENT_THRESHOLD_S,
) -> AgreementResult:
    """Compare a recording's header timestamps against its index start/end.

    Missing values on either side are treated as "cannot compare" (agree,
    no reason) rather than a disagreement — absence of an index or header
    is a coverage-tier fact recorded elsewhere (``FrameRef.source``), not a
    clock disagreement.
    """
    diffs: list[tuple[str, float]] = []
    if header_start_us is not None and index_start_us is not None:
        diffs.append(("start", abs(header_start_us - index_start_us) / 1_000_000))
    if header_end_us is not None and index_end_us is not None:
        diffs.append(("end", abs(header_end_us - index_end_us) / 1_000_000))

    if not diffs:
        return AgreementResult(agree=True, max_diff_s=0.0, reason=None)

    label, max_diff = max(diffs, key=lambda d: d[1])
    if max_diff > threshold_s:
        reason = (
            f"header/index disagree by {max_diff:.1f}s at recording {label} "
            f"(threshold {threshold_s:.1f}s)"
        )
        return AgreementResult(agree=False, max_diff_s=max_diff, reason=reason)
    return AgreementResult(agree=True, max_diff_s=max_diff, reason=None)


# --------------------------------------------------------------------------
# Robust median (docs §4 step 4: osd_offset = median(...), MAD outliers)
# --------------------------------------------------------------------------


def robust_median_offset(
    diffs_us: Sequence[int], *, mad_k: float = 3.5
) -> tuple[int | None, float]:
    """Median of ``diffs_us`` after removing MAD outliers.

    Returns ``(median_offset_us, residual_ms)`` where ``residual_ms`` is the
    median absolute deviation (in ms) of the surviving samples around the
    median — a measure of how tight the agreement is. ``(None, 0.0)`` if
    ``diffs_us`` is empty.
    """
    if not diffs_us:
        return None, 0.0

    values = sorted(diffs_us)
    median = _median(values)
    abs_devs = [abs(v - median) for v in values]
    mad = _median(abs_devs)

    if mad == 0:
        survivors = values
    else:
        # 1.4826 scales MAD to be a consistent estimator of std-dev for
        # normally-distributed data; mad_k standard deviations is the
        # outlier cutoff.
        cutoff = mad_k * 1.4826 * mad
        survivors = [v for v in values if abs(v - median) <= cutoff]
        if not survivors:
            survivors = values

    final_median = _median(survivors)
    residual_us = _median([abs(v - final_median) for v in survivors])
    return int(round(final_median)), residual_us / 1000.0


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


# --------------------------------------------------------------------------
# Confidence formula (docs §4 step 6)
# --------------------------------------------------------------------------


def build_clock_model(
    *,
    id: str,
    image_id: str,
    channel: int | None,
    segments: Sequence[ClockSegment],
    osd_offset_us: int | None,
    confidence: float,
    residual_ms: float,
    method: str,
) -> ClockModel:
    """Convenience constructor for a fresh (non-overridden) ``ClockModel``."""
    return ClockModel(
        id=id,
        image_id=image_id,
        channel=channel,
        segments=list(segments),
        osd_offset_us=osd_offset_us,
        confidence=confidence,
        residual_ms=residual_ms,
        method=method,
        overridden_by=None,
    )


def compute_confidence(
    *,
    has_seizure_anchor: bool,
    header_index_agree: bool,
    osd_residual_ok: bool,
    unexplained_jumps: int = 0,
) -> float:
    """docs/03-AI-TIMELINE.md §4 step 6.

    Starts at 0.5 with a seizure anchor (0.2 without), +0.2 if header/index
    agree, +0.2 if the OSD residual is under 1s after correction, -0.2 per
    unexplained jump > 5s. Clamped to ``[0, 1]``.
    """
    confidence = 0.5 if has_seizure_anchor else 0.2
    if header_index_agree:
        confidence += 0.2
    if osd_residual_ok:
        confidence += 0.2
    confidence -= 0.2 * unexplained_jumps
    return max(0.0, min(1.0, confidence))


# --------------------------------------------------------------------------
# Normalisation over a frame table (docs §4 step 5)
# --------------------------------------------------------------------------

#: Confidence multipliers applied to a channel's ClockModel.confidence,
#: depending on which clock a frame's normalised time was derived from.
#: Tier A (header) and Tier B (index-only) are close to the model's own
#: confidence; OSD-only and interpolated frames are visibly less certain.
#: This scale is an engineering choice (not specified verbatim in docs §4)
#: recorded in docs/progress/A1.md "Decisions".
_TIER_HEADER_MULT = 1.0
_TIER_INDEX_MULT = 0.9
_TIER_OSD_MULT = 0.7
_TIER_INTERPOLATED_MULT = 0.3
_TIER_UNKNOWN_CONFIDENCE = 0.0


def normalise_frame_table(
    table: pa.Table, clock_models: Mapping[int | None, ClockModel]
) -> pa.Table:
    """Fill ``ts_norm_us``/``norm_confidence`` for every row of a frame table.

    ``table`` follows ``pramaan_core.frames.SCHEMA`` (one row per
    ``FrameRef`` plus the four AI columns). ``clock_models`` maps
    ``channel -> ClockModel`` (``None`` key = a whole-device model used for
    rows whose channel has no dedicated model, or whose own ``channel`` is
    ``None``).

    Per docs §4 step 5: normalised time = device time − segment offset.
    Frames with neither header nor index time (Tier C) take
    ``osd_ts − osd_offset`` when OSD succeeded, else linear interpolation
    between the nearest same-channel neighbours with a known normalised
    time (ordered by ``payload_offset``, since Tier C rows have no header
    timestamp to sort chronologically by — see docs/progress/A1.md
    "Decisions"), each with reduced confidence. Row order and every other
    column are left untouched (CLAUDE.md rule 5: no resorting here — the
    table's on-disk sort order is a contract owned by ``pramaan_core.frames``).
    """
    rows: list[dict[str, object]] = table.to_pylist()

    for row in rows:
        channel = _as_int(row["channel"])
        model = clock_models.get(channel)
        if model is None:
            model = clock_models.get(None)
        if model is None:
            row["ts_norm_us"] = None
            row["norm_confidence"] = _TIER_UNKNOWN_CONFIDENCE
            continue

        device_ts = _as_int(row.get("ts_header_us"))
        mult = _TIER_HEADER_MULT
        if device_ts is None:
            device_ts = _as_int(row.get("ts_index_us"))
            mult = _TIER_INDEX_MULT

        if device_ts is not None:
            offset = offset_for_device_ts(model.segments, device_ts)
            row["ts_norm_us"] = device_ts - offset
            row["norm_confidence"] = round(model.confidence * mult, 6)
            continue

        osd_ts = _as_int(row.get("ts_osd_us"))
        if osd_ts is not None and model.osd_offset_us is not None:
            row["ts_norm_us"] = osd_ts - model.osd_offset_us
            row["norm_confidence"] = round(model.confidence * _TIER_OSD_MULT, 6)
            continue

        # Unresolved for now; filled by interpolation below.
        row["ts_norm_us"] = None
        row["norm_confidence"] = None

    _interpolate_missing(rows)

    columns = {name: [row[name] for row in rows] for name in table.schema.names}
    return pa.table(columns, schema=table.schema)


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"expected int or None, got bool {value!r}")
    if isinstance(value, int):
        return value
    raise TypeError(f"expected int or None, got {value!r}")


def _required_int(value: object) -> int:
    result = _as_int(value)
    if result is None:
        raise TypeError("expected int, got None")
    return result


def _interpolate_missing(rows: list[dict[str, object]]) -> None:
    by_channel: dict[int | None, list[int]] = {}
    for i, row in enumerate(rows):
        by_channel.setdefault(_as_int(row["channel"]), []).append(i)

    for indices in by_channel.values():
        ordered = sorted(indices, key=lambda i: _required_int(rows[i]["payload_offset"]))
        known = [i for i in ordered if rows[i]["ts_norm_us"] is not None]
        if not known:
            for i in ordered:
                if rows[i]["ts_norm_us"] is None:
                    rows[i]["norm_confidence"] = _TIER_UNKNOWN_CONFIDENCE
            continue

        known_set = set(known)
        for pos, i in enumerate(ordered):
            if i in known_set:
                continue
            prev_i = next(
                (ordered[p] for p in range(pos - 1, -1, -1) if ordered[p] in known_set), None
            )
            next_i = next(
                (ordered[p] for p in range(pos + 1, len(ordered)) if ordered[p] in known_set), None
            )

            if prev_i is not None and next_i is not None:
                x0 = _required_int(rows[prev_i]["payload_offset"])
                x1 = _required_int(rows[next_i]["payload_offset"])
                y0 = _required_int(rows[prev_i]["ts_norm_us"])
                y1 = _required_int(rows[next_i]["ts_norm_us"])
                x = _required_int(rows[i]["payload_offset"])
                interpolated: float = (
                    float(y0) if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
                )
                rows[i]["ts_norm_us"] = int(round(interpolated))
                rows[i]["norm_confidence"] = round(_TIER_INTERPOLATED_MULT, 6)
            elif prev_i is not None:
                rows[i]["ts_norm_us"] = rows[prev_i]["ts_norm_us"]
                rows[i]["norm_confidence"] = round(_TIER_INTERPOLATED_MULT * 0.5, 6)
            elif next_i is not None:
                rows[i]["ts_norm_us"] = rows[next_i]["ts_norm_us"]
                rows[i]["norm_confidence"] = round(_TIER_INTERPOLATED_MULT * 0.5, 6)
            else:  # pragma: no cover — unreachable, `known` non-empty implies one exists
                rows[i]["norm_confidence"] = _TIER_UNKNOWN_CONFIDENCE
