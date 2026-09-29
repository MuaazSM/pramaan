"""Frame index: Parquet writer/reader (pyarrow) + DuckDB query helper.

One file per image at ``<case_dir>/index/frames-<image_id>.parquet``, one
row per :class:`~pramaan_core.models.FrameRef` plus four columns the AI
workstream fills in later (``ts_osd_us``, ``ts_norm_us``,
``norm_confidence``, ``motion_score`` — docs/03-AI-TIMELINE.md §3), sorted
by ``(channel, ts_header_us, payload_offset)`` for deterministic output
(CLAUDE.md rule 5: sort before serialising).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pramaan_core.models import FrameRef

#: Columns AI fills in after normalisation / motion triage.
TIMELINE_COLUMNS: tuple[str, ...] = ("ts_osd_us", "ts_norm_us", "norm_confidence", "motion_score")

#: FrameRef's own fields, in declaration order.
_FRAME_FIELDS: tuple[str, ...] = tuple(FrameRef.model_fields.keys())

SCHEMA = pa.schema(
    [
        pa.field("frame_id", pa.string()),
        pa.field("image_id", pa.string()),
        pa.field("channel", pa.int32()),
        pa.field("stream", pa.string()),
        pa.field("codec", pa.string()),
        pa.field("frame_type", pa.string()),
        pa.field("header_offset", pa.int64()),
        pa.field("payload_offset", pa.int64()),
        pa.field("payload_len", pa.int64()),
        pa.field("ts_header_us", pa.int64()),
        pa.field("ts_index_us", pa.int64()),
        pa.field("width", pa.int32()),
        pa.field("height", pa.int32()),
        pa.field("source", pa.string()),
        pa.field("recording_id", pa.string()),
        pa.field("deleted", pa.bool_()),
        pa.field("ts_osd_us", pa.int64()),
        pa.field("ts_norm_us", pa.int64()),
        pa.field("norm_confidence", pa.float64()),
        pa.field("motion_score", pa.float64()),
    ]
)


def index_path(case_dir: str | Path, image_id: str) -> Path:
    """Path to the Parquet frame index for ``image_id`` under ``case_dir``."""
    return Path(case_dir) / "index" / f"frames-{image_id}.parquet"


def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
    channel = row["channel"] if row["channel"] is not None else -1
    ts = row["ts_header_us"] if row["ts_header_us"] is not None else -1
    return (channel, ts, row["payload_offset"])


def write_frames(case_dir: str | Path, image_id: str, frames: list[FrameRef]) -> Path:
    """Write ``frames`` to the Parquet frame index for ``image_id``.

    Rows are sorted by ``(channel, ts_header_us, payload_offset)``; the four
    timeline columns are written as null (AI fills them in later, in place,
    once normalisation/motion-triage run). Overwrites any existing index
    file for this image — regenerating the whole index from the same input
    always yields the same rows (determinism, CLAUDE.md rule 5).
    """
    rows = [frame.model_dump() for frame in frames]
    rows.sort(key=_sort_key)

    columns: dict[str, list[Any]] = {name: [] for name in SCHEMA.names}
    for row in rows:
        for name in _FRAME_FIELDS:
            columns[name].append(row[name])
        for name in TIMELINE_COLUMNS:
            columns[name].append(None)

    table = pa.table(columns, schema=SCHEMA)
    path = index_path(case_dir, image_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path


def read_frames(case_dir: str | Path, image_id: str) -> list[dict[str, Any]]:
    """Read the Parquet frame index for ``image_id`` back as row dicts."""
    table = pq.read_table(index_path(case_dir, image_id))
    result: list[dict[str, Any]] = table.to_pylist()
    return result


def query(case_dir: str | Path, sql: str, image_id: str | None = None) -> list[dict[str, Any]]:
    """Run a read-only DuckDB SQL query over the frame index.

    The query sees a view named ``frames``: the single Parquet file for
    ``image_id`` when given, otherwise every ``frames-*.parquet`` file under
    ``<case_dir>/index/`` unioned together (DuckDB's ``read_parquet`` glob
    support), so cross-channel / cross-image queries work without the
    caller globbing files itself.
    """
    import duckdb

    index_dir = Path(case_dir) / "index"
    glob = (
        str(index_path(case_dir, image_id))
        if image_id is not None
        else str(index_dir / "frames-*.parquet")
    )
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"CREATE VIEW frames AS SELECT * FROM read_parquet('{glob}')")
        result: list[dict[str, Any]] = con.execute(sql).to_arrow_table().to_pylist()
        return result
    finally:
        con.close()
