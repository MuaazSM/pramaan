"""Table-driven tests for clock segment reconstruction, header/index
agreement, the confidence formula, robust median offset, and frame-table
normalisation (docs/03-AI-TIMELINE.md §4, §9's "Clock segments" and
"Normalisation" acceptance rows).
"""

from __future__ import annotations

import pyarrow as pa
import pytest
from pramaan_core.frames import SCHEMA
from pramaan_core.models import ClockModel, ClockObservation, ClockSegment, LogEvent
from pramaan_timeline.clock import (
    AgreementResult,
    build_clock_model,
    compute_confidence,
    header_index_agreement,
    normalise_frame_table,
    offset_for_device_ts,
    reconstruct_segments,
    robust_median_offset,
)

IMG = "img_" + "a" * 16


def _seizure(device_ts_us: int, offset_us: int) -> ClockObservation:
    return ClockObservation(
        id="obs_seizure",
        image_id=IMG,
        channel=None,
        source="seizure",
        device_ts_us=device_ts_us,
        reference_ts_us=device_ts_us - offset_us,
        offset_us=offset_us,
        weight=1.0,
        details={},
    )


def _time_change(
    ts_device_us: int, old_ts_us: int, new_ts_us: int, event_id: str = "log_1"
) -> LogEvent:
    return LogEvent(
        id=event_id,
        image_id=IMG,
        ts_device_us=ts_device_us,
        kind="time_change",
        user="admin",
        channel=None,
        details={"old_ts_us": old_ts_us, "new_ts_us": new_ts_us},
        offset=0,
    )


HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US


class TestReconstructSegments:
    def test_no_time_changes_single_open_segment(self) -> None:
        seizure = _seizure(device_ts_us=10 * DAY_US, offset_us=312_000_000)  # +5m12s
        segments = reconstruct_segments(seizure, [])
        assert segments == [
            ClockSegment(from_device_us=None, to_device_us=None, offset_us=312_000_000)
        ]

    def test_clock_set_back_one_hour(self) -> None:
        """docs §9 acceptance row: "clock set back 1 h" must reconstruct
        exactly. Device clock read 02:00 then jumped back to 01:00 at
        device time ``t`` (mid-recording); seizure offset applies after."""
        t = 5 * DAY_US + 2 * HOUR_US  # device displayed 02:00 on day 5
        old_ts = t
        new_ts = t - HOUR_US  # jumped back to 01:00
        seizure = _seizure(device_ts_us=10 * DAY_US, offset_us=312_000_000)
        change = _time_change(ts_device_us=t, old_ts_us=old_ts, new_ts_us=new_ts)

        segments = reconstruct_segments(seizure, [change])

        assert len(segments) == 2
        before, after = segments
        # offset_before = offset_after - (new - old) = 312_000_000 - (-3600e6)
        assert before == ClockSegment(
            from_device_us=None, to_device_us=old_ts, offset_us=312_000_000 + HOUR_US
        )
        assert after == ClockSegment(
            from_device_us=new_ts, to_device_us=None, offset_us=312_000_000
        )
        # True time must be continuous across the boundary: true = device - offset.
        true_at_boundary_before = old_ts - before.offset_us
        true_at_boundary_after = new_ts - after.offset_us
        assert true_at_boundary_before == true_at_boundary_after

    def test_two_time_changes_walks_backwards_correctly(self) -> None:
        seizure = _seizure(device_ts_us=20 * DAY_US, offset_us=0)
        change_a = _time_change(5 * DAY_US, 5 * DAY_US, 5 * DAY_US - HOUR_US, "log_a")
        change_b = _time_change(12 * DAY_US, 12 * DAY_US, 12 * DAY_US + 2 * HOUR_US, "log_b")

        segments = reconstruct_segments(seizure, [change_a, change_b])
        assert len(segments) == 3

        # oldest-first
        seg0, seg1, seg2 = segments
        assert seg0.to_device_us == 5 * DAY_US
        assert seg1.from_device_us == 5 * DAY_US - HOUR_US
        assert seg1.to_device_us == 12 * DAY_US
        assert seg2.from_device_us == 12 * DAY_US + 2 * HOUR_US
        assert seg2.to_device_us is None
        assert seg2.offset_us == 0

        # continuity at each boundary
        assert seg0.to_device_us - seg0.offset_us == seg1.from_device_us - seg1.offset_us
        assert seg1.to_device_us - seg1.offset_us == seg2.from_device_us - seg2.offset_us

    def test_ignores_non_time_change_events(self) -> None:
        seizure = _seizure(device_ts_us=10 * DAY_US, offset_us=0)
        other = LogEvent(
            id="log_x",
            image_id=IMG,
            ts_device_us=DAY_US,
            kind="power_on",
            user=None,
            channel=None,
            details={},
            offset=0,
        )
        segments = reconstruct_segments(seizure, [other])
        assert segments == [ClockSegment(from_device_us=None, to_device_us=None, offset_us=0)]

    def test_rejects_non_seizure_observation(self) -> None:
        not_seizure = ClockObservation(
            id="obs",
            image_id=IMG,
            channel=None,
            source="osd",
            device_ts_us=0,
            reference_ts_us=None,
            offset_us=0,
            weight=1.0,
            details={},
        )
        with pytest.raises(ValueError, match="seizure"):
            reconstruct_segments(not_seizure, [])


class TestOffsetForDeviceTs:
    def test_looks_up_correct_segment(self) -> None:
        segments = [
            ClockSegment(from_device_us=None, to_device_us=100, offset_us=10),
            ClockSegment(from_device_us=100, to_device_us=None, offset_us=20),
        ]
        assert offset_for_device_ts(segments, 50) == 10
        assert offset_for_device_ts(segments, 100) == 20
        assert offset_for_device_ts(segments, 1000) == 20

    def test_falls_back_before_earliest_segment(self) -> None:
        segments = [ClockSegment(from_device_us=1000, to_device_us=None, offset_us=5)]
        assert offset_for_device_ts(segments, 0) == 5


class TestHeaderIndexAgreement:
    def test_agrees_within_threshold(self) -> None:
        result = header_index_agreement(1_000_000, 2_000_000, 1_500_000, 2_500_000)
        assert result == AgreementResult(agree=True, max_diff_s=0.5, reason=None)

    def test_disagrees_beyond_threshold(self) -> None:
        result = header_index_agreement(0, 10_000_000, 5_000_000, 10_000_000)
        assert result.agree is False
        assert result.max_diff_s == 5.0
        assert result.reason is not None and "disagree" in result.reason

    def test_missing_values_are_not_a_disagreement(self) -> None:
        result = header_index_agreement(None, None, None, None)
        assert result == AgreementResult(agree=True, max_diff_s=0.0, reason=None)


class TestComputeConfidence:
    @pytest.mark.parametrize(
        ("has_seizure", "header_agree", "osd_ok", "jumps", "expected"),
        [
            (True, True, True, 0, 0.9),
            (True, False, False, 0, 0.5),
            (False, False, False, 0, 0.2),
            (True, True, True, 1, 0.7),
            (True, True, True, 5, 0.0),  # clamped, not negative
            (False, True, True, 0, 0.6),
        ],
    )
    def test_formula(
        self, has_seizure: bool, header_agree: bool, osd_ok: bool, jumps: int, expected: float
    ) -> None:
        confidence = compute_confidence(
            has_seizure_anchor=has_seizure,
            header_index_agree=header_agree,
            osd_residual_ok=osd_ok,
            unexplained_jumps=jumps,
        )
        assert confidence == pytest.approx(expected)

    def test_never_exceeds_one(self) -> None:
        confidence = compute_confidence(
            has_seizure_anchor=True,
            header_index_agree=True,
            osd_residual_ok=True,
            unexplained_jumps=0,
        )
        assert confidence <= 1.0


class TestRobustMedianOffset:
    def test_empty_returns_none(self) -> None:
        assert robust_median_offset([]) == (None, 0.0)

    def test_simple_median(self) -> None:
        offset, residual_ms = robust_median_offset([10, 12, 11, 9, 13])
        assert offset == 11
        assert residual_ms >= 0.0

    def test_removes_mad_outliers(self) -> None:
        # Tight cluster around 37_000_000us (+37s) with one wild outlier.
        diffs = [37_000_000, 37_050_000, 36_980_000, 37_020_000, 999_000_000]
        offset, residual_ms = robust_median_offset(diffs)
        assert offset is not None
        assert abs(offset - 37_000_000) < 100_000  # within 0.1s of the true cluster
        assert residual_ms < 1000  # tight cluster -> small residual


class TestBuildClockModel:
    def test_builds_fresh_unoverridden_model(self) -> None:
        segments = [ClockSegment(from_device_us=None, to_device_us=None, offset_us=0)]
        model = build_clock_model(
            id="clk_1",
            image_id=IMG,
            channel=2,
            segments=segments,
            osd_offset_us=37_000_000,
            confidence=0.9,
            residual_ms=5.0,
            method="seizure+time_change+osd",
        )
        assert isinstance(model, ClockModel)
        assert model.overridden_by is None
        assert model.segments == segments


def _table(rows: list[dict[str, object]]) -> pa.Table:
    return pa.table({name: [row.get(name) for row in rows] for name in SCHEMA.names}, schema=SCHEMA)


def _frame_row(
    frame_id: str,
    channel: int | None,
    payload_offset: int,
    *,
    ts_header_us: int | None = None,
    ts_index_us: int | None = None,
    ts_osd_us: int | None = None,
) -> dict[str, object]:
    return {
        "frame_id": frame_id,
        "image_id": IMG,
        "channel": channel,
        "stream": None,
        "codec": "h264",
        "frame_type": "I",
        "header_offset": None,
        "payload_offset": payload_offset,
        "payload_len": 100,
        "ts_header_us": ts_header_us,
        "ts_index_us": ts_index_us,
        "width": None,
        "height": None,
        "source": "index",
        "recording_id": None,
        "deleted": False,
        "ts_osd_us": ts_osd_us,
        "ts_norm_us": None,
        "norm_confidence": None,
        "motion_score": None,
    }


class TestNormaliseFrameTable:
    def _model(self, offset_us: int = 100, osd_offset_us: int | None = None) -> ClockModel:
        return build_clock_model(
            id="clk",
            image_id=IMG,
            channel=1,
            segments=[ClockSegment(from_device_us=None, to_device_us=None, offset_us=offset_us)],
            osd_offset_us=osd_offset_us,
            confidence=0.9,
            residual_ms=0.0,
            method="test",
        )

    def test_header_tier(self) -> None:
        rows = [_frame_row("f1", 1, 0, ts_header_us=1000)]
        table = _table(rows)

        result = normalise_frame_table(table, {1: self._model(offset_us=100)})
        out = result.to_pylist()
        assert out[0]["ts_norm_us"] == 900
        assert out[0]["norm_confidence"] == pytest.approx(0.9)

    def test_index_tier_used_when_header_missing(self) -> None:
        rows = [_frame_row("f1", 1, 0, ts_index_us=2000)]
        table = _table(rows)
        result = normalise_frame_table(table, {1: self._model(offset_us=100)})
        out = result.to_pylist()
        assert out[0]["ts_norm_us"] == 1900
        assert out[0]["norm_confidence"] == pytest.approx(0.9 * 0.9)

    def test_osd_tier_used_when_no_header_or_index(self) -> None:
        rows = [_frame_row("f1", 1, 0, ts_osd_us=5000)]
        table = _table(rows)
        result = normalise_frame_table(table, {1: self._model(offset_us=100, osd_offset_us=37)})
        out = result.to_pylist()
        assert out[0]["ts_norm_us"] == 5000 - 37
        assert out[0]["norm_confidence"] == pytest.approx(0.9 * 0.7)

    def test_interpolates_tier_c_frames_between_known_neighbours(self) -> None:
        rows = [
            _frame_row("f1", 1, payload_offset=0, ts_header_us=0),
            _frame_row("f2", 1, payload_offset=100, ts_header_us=None),  # carved, Tier C
            _frame_row("f3", 1, payload_offset=200, ts_header_us=1000),
        ]
        table = _table(rows)
        result = normalise_frame_table(table, {1: self._model(offset_us=0)})
        out = result.to_pylist()
        by_id = {row["frame_id"]: row for row in out}
        assert by_id["f1"]["ts_norm_us"] == 0
        assert by_id["f3"]["ts_norm_us"] == 1000
        # f2 sits halfway by payload_offset -> halfway in normalised time.
        assert by_id["f2"]["ts_norm_us"] == 500
        assert by_id["f2"]["norm_confidence"] < by_id["f1"]["norm_confidence"]

    def test_unresolvable_channel_gets_zero_confidence(self) -> None:
        rows = [_frame_row("f1", 9, 0, ts_header_us=1000)]
        table = _table(rows)
        result = normalise_frame_table(table, {1: self._model()})
        out = result.to_pylist()
        assert out[0]["ts_norm_us"] is None
        assert out[0]["norm_confidence"] == 0.0

    def test_row_order_and_other_columns_untouched(self) -> None:
        rows = [
            _frame_row("f1", 1, 0, ts_header_us=1000),
            _frame_row("f2", 1, 10, ts_header_us=2000),
        ]
        table = _table(rows)
        result = normalise_frame_table(table, {1: self._model(offset_us=0)})
        out = result.to_pylist()
        assert [row["frame_id"] for row in out] == ["f1", "f2"]
        assert [row["payload_len"] for row in out] == [100, 100]
