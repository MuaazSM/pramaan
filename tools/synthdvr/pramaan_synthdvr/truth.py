"""Ground truth writer (docs/05-INFRA-QA.md §4.4): `corpus/truth/<image>.json`
plus `corpus/truth/<image>.frames.parquet`. Parsers never read these; they
exist for `tests/validation` and for scoring later CORE/AI tasks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


@dataclass
class TruthFrame:
    channel: int
    ts_device_us: int
    ts_true_us: int
    ts_osd_us: int
    header_offset: int | None
    payload_offset: int
    payload_len: int
    payload_sha256: str
    frame_type: str  # "I" | "P"
    recording_id: str
    deleted: bool
    overwritten: bool


@dataclass
class TruthBuilder:
    image: str
    family: str
    tier: str
    device_model: str | None
    device_serial: str | None
    seizure_dvr_displayed: str
    seizure_reference: str
    clock_segments: list[dict[str, Any]] = field(default_factory=list)
    time_changes: list[dict[str, Any]] = field(default_factory=list)
    osd_drift_s: dict[str, float] = field(default_factory=dict)
    channels: list[dict[str, Any]] = field(default_factory=list)
    recordings: list[dict[str, Any]] = field(default_factory=list)
    deletions: list[dict[str, Any]] = field(default_factory=list)
    log_events: list[dict[str, Any]] = field(default_factory=list)
    motion_events: list[dict[str, Any]] = field(default_factory=list)
    hidden_layout: dict[str, Any] | None = None
    frames: list[TruthFrame] = field(default_factory=list)

    def add_frame(self, f: TruthFrame) -> None:
        self.frames.append(f)

    def to_json_dict(self, sha256: str) -> dict[str, Any]:
        return {
            "image": self.image,
            "family": self.family,
            "tier": self.tier,
            "sha256": sha256,
            "device": {"model": self.device_model, "serial": self.device_serial},
            "seizure": {
                "dvr_displayed": self.seizure_dvr_displayed,
                "reference": self.seizure_reference,
            },
            "clock": {
                "segments": self.clock_segments,
                "time_changes": self.time_changes,
                "osd_drift_s": self.osd_drift_s,
            },
            "channels": self.channels,
            "recordings": self.recordings,
            "deletions": self.deletions,
            "log_events": self.log_events,
            "motion_events": self.motion_events,
            "hidden_layout": self.hidden_layout,
        }

    def write(self, truth_dir: Path, image_path: Path) -> None:
        truth_dir.mkdir(parents=True, exist_ok=True)
        sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
        doc = self.to_json_dict(sha256)
        json_path = truth_dir / f"{self.image}.json"
        json_path.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
        self._write_frames_parquet(truth_dir / f"{self.image}.frames.parquet")

    _SCHEMA = pa.schema(
        [
            ("channel", pa.int32()),
            ("ts_device_us", pa.int64()),
            ("ts_true_us", pa.int64()),
            ("ts_osd_us", pa.int64()),
            ("header_offset", pa.int64()),
            ("payload_offset", pa.int64()),
            ("payload_len", pa.int64()),
            ("payload_sha256", pa.string()),
            ("frame_type", pa.string()),
            ("recording_id", pa.string()),
            ("deleted", pa.bool_()),
            ("overwritten", pa.bool_()),
        ]
    )

    def _write_frames_parquet(self, path: Path) -> None:
        rows = sorted(self.frames, key=lambda f: (f.channel, f.ts_device_us, f.payload_offset))
        cols: dict[str, list[Any]] = {name: [] for name in self._SCHEMA.names}
        for r in rows:
            cols["channel"].append(r.channel)
            cols["ts_device_us"].append(r.ts_device_us)
            cols["ts_true_us"].append(r.ts_true_us)
            cols["ts_osd_us"].append(r.ts_osd_us)
            cols["header_offset"].append(r.header_offset)
            cols["payload_offset"].append(r.payload_offset)
            cols["payload_len"].append(r.payload_len)
            cols["payload_sha256"].append(r.payload_sha256)
            cols["frame_type"].append(r.frame_type)
            cols["recording_id"].append(r.recording_id)
            cols["deleted"].append(r.deleted)
            cols["overwritten"].append(r.overwritten)
        table = pa.table(cols, schema=self._SCHEMA)
        pq.write_table(table, path, compression="zstd")


def check_self_consistency(image_path: Path, truth_dir: Path, image_name: str) -> list[str]:
    """Every *recoverable* truth frame's payload hash must be found at its
    recorded offset in the image file (acceptance criterion in the Q1 task
    brief). Frames marked ``overwritten`` are ground truth about history
    (what a later write physically clobbered) and are expected to mismatch
    — that's the point of an overwrite/format fixture — so they're skipped
    here; everything else must be byte-exact. Returns a list of error
    strings (empty = consistent)."""
    errors: list[str] = []
    frames_path = truth_dir / f"{image_name}.frames.parquet"
    if not frames_path.exists():
        return [f"missing {frames_path}"]
    table = pq.read_table(frames_path)
    data = image_path.read_bytes()
    for row in table.to_pylist():
        if row["overwritten"]:
            continue
        off, ln, expect = row["payload_offset"], row["payload_len"], row["payload_sha256"]
        actual = hashlib.sha256(data[off : off + ln]).hexdigest()
        if actual != expect:
            errors.append(
                f"{image_name}: frame at offset {off} (channel {row['channel']}) "
                f"hash mismatch: expected {expect}, got {actual}"
            )
    return errors
