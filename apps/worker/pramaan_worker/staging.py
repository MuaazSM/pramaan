"""JSON staging files for intermediate ``FrameRef`` lists between pipeline
stages (docs/02-BACKEND.md §6).

A stage's output must be readable by a later stage even when the two run in
different processes (``JOB_BACKEND=dramatiq`` runs each stage as a separate
message/actor invocation — see ``pramaan_worker.runner``'s "state must live
on disk or in the DB, never in closures"), so intermediate ``FrameRef``
lists are written here rather than passed through Python return values.
Each stage that discovers frames (``parse_index`` → ``index``, ``carve`` →
``carved``) writes its own file; ``frame_index`` reads every stage's file
back and merges them before writing the final Parquet index
(``pramaan_core.frames.write_frames``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pramaan_core.models import FrameRef

#: Every stage key that contributes frames, in the order they're merged.
STAGE_KEYS: tuple[str, ...] = ("index", "carved", "inferred")


def _staging_path(case_dir: str | Path, image_id: str, stage_key: str) -> Path:
    return Path(case_dir) / "index" / "_staging" / f"{image_id}.{stage_key}.json"


def write_frame_stage(
    case_dir: str | Path, image_id: str, stage_key: str, frames: list[FrameRef]
) -> Path:
    """Persist ``frames`` for ``stage_key`` (one of :data:`STAGE_KEYS`),
    sorted for deterministic output (CLAUDE.md rule 5)."""
    path = _staging_path(case_dir, image_id, stage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = [f.model_dump() for f in frames]

    def _key(r: dict[str, Any]) -> tuple[int, int]:
        return (r["channel"] if r["channel"] is not None else -1, r["payload_offset"])

    rows.sort(key=_key)
    path.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
    return path


def read_frame_stage(case_dir: str | Path, image_id: str, stage_key: str) -> list[FrameRef]:
    path = _staging_path(case_dir, image_id, stage_key)
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [FrameRef(**row) for row in rows]


def read_all_frames(case_dir: str | Path, image_id: str) -> list[FrameRef]:
    """Merge every stage's frames for ``image_id``, in :data:`STAGE_KEYS`
    order (``frame_index`` sorts again by its own key before writing, so
    this order only affects ties)."""
    out: list[FrameRef] = []
    for key in STAGE_KEYS:
        out.extend(read_frame_stage(case_dir, image_id, key))
    return out
