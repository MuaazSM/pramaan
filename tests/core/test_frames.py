"""Parquet frame index round-trip + DuckDB query helper tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pramaan_core.frames import index_path, query, read_frames, write_frames
from pramaan_core.models import FrameRef

IMAGE_ID = "img_" + "a" * 16


def _frame(channel: int, ts: int, offset: int, **overrides: Any) -> FrameRef:
    base: dict[str, Any] = dict(
        frame_id=f"f{offset:08x}" + "0" * 16,
        image_id=IMAGE_ID,
        channel=channel,
        stream="main",
        codec="h264",
        frame_type="I",
        header_offset=offset - 40,
        payload_offset=offset,
        payload_len=100,
        ts_header_us=ts,
        ts_index_us=ts,
        width=1920,
        height=1080,
        source="index",
        recording_id=None,
        deleted=False,
    )
    base.update(overrides)
    return FrameRef(**base)


def test_write_read_round_trip_sorted(tmp_path: Path) -> None:
    frames = [
        _frame(channel=1, ts=2000, offset=2000),
        _frame(channel=0, ts=1000, offset=1000),
        _frame(channel=1, ts=1000, offset=1500),
    ]
    path = write_frames(tmp_path, IMAGE_ID, frames)
    assert path == index_path(tmp_path, IMAGE_ID)
    assert path.exists()

    rows = read_frames(tmp_path, IMAGE_ID)
    assert [r["channel"] for r in rows] == [0, 1, 1]
    assert [r["payload_offset"] for r in rows] == [1000, 1500, 2000]
    # Timeline columns start out null; AI fills them in later.
    assert rows[0]["ts_osd_us"] is None
    assert rows[0]["norm_confidence"] is None
    assert rows[0]["motion_score"] is None
    assert rows[0]["frame_id"] == frames[1].frame_id


def test_query_with_duckdb(tmp_path: Path) -> None:
    frames = [_frame(channel=0, ts=1000, offset=1000), _frame(channel=1, ts=2000, offset=2000)]
    write_frames(tmp_path, IMAGE_ID, frames)

    rows = query(
        tmp_path,
        "SELECT channel, count(*) AS n FROM frames GROUP BY channel ORDER BY channel",
        image_id=IMAGE_ID,
    )
    assert rows == [{"channel": 0, "n": 1}, {"channel": 1, "n": 1}]


def test_query_across_multiple_images_without_image_id(tmp_path: Path) -> None:
    write_frames(tmp_path, "img_" + "a" * 16, [_frame(channel=0, ts=1000, offset=1000)])
    write_frames(tmp_path, "img_" + "b" * 16, [_frame(channel=0, ts=1000, offset=2000)])

    rows = query(tmp_path, "SELECT count(*) AS n FROM frames")
    assert rows == [{"n": 2}]


def test_write_frames_is_deterministic_across_input_order(tmp_path: Path) -> None:
    frames = [_frame(channel=0, ts=1000, offset=1000), _frame(channel=1, ts=2000, offset=2000)]

    write_frames(tmp_path / "a", IMAGE_ID, frames)
    write_frames(tmp_path / "b", IMAGE_ID, list(reversed(frames)))

    assert read_frames(tmp_path / "a", IMAGE_ID) == read_frames(tmp_path / "b", IMAGE_ID)
