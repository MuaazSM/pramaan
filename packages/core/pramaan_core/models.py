"""Shared Pydantic models for Pramaan (docs/01-FORENSIC-CORE.md §3.1,
docs/03-AI-TIMELINE.md §3 — kept in one file so every workstream has one
import path: ``pramaan_core.models``).

These are frozen (immutable after construction) and reject unknown fields.
Callers build a new instance to change one, rather than mutating in place —
that keeps derived artefacts (which embed these as JSON) safe to hash and
compare (CLAUDE.md rule 5, determinism).

Change this file only additively (new optional fields, new models); it is a
frozen shared contract per CLAUDE.md and docs/01-FORENSIC-CORE.md §3.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    """Base class for every shared model: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Provenance(_Frozen):
    """Records how a derived artefact was produced (CLAUDE.md rule 4)."""

    parent_sha256: str | None  # input artefact hash
    tool: str  # "pramaan"
    tool_version: str  # from package metadata
    step: str  # e.g. "recovery.carve_annexb"
    params: dict[str, Any]  # sorted, JSON-serialisable
    created_utc: str  # ISO-8601; excluded from content hashes


class ByteRange(_Frozen):
    offset: int
    length: int


class EvidenceImage(_Frozen):
    id: str  # "img_" + sha256[:16]
    path: str
    format: Literal["raw", "e01"]
    size_bytes: int
    sha256: str
    md5: str
    acquired_utc: str
    verified: bool


class VendorMatch(_Frozen):
    family: str  # "hiksim" | "dhsim" | "hwsim" | "xsim" | "gensim" | ...
    display_name: str  # "Hikvision-like (synthetic)"
    platform: str | None  # OEM lineage, e.g. "hikvision"
    tier: Literal["A", "B", "C"]
    confidence: float  # 0..1
    evidence: list[str]  # human-readable reasons, e.g. "signature HIKVISION@HANGZHOU at 0x210"
    model: str | None
    serial: str | None
    fs_version: str | None


class Recording(_Frozen):
    id: str  # stable hash of (image_id, channel, start, offset)
    image_id: str
    channel: int
    stream: Literal["main", "sub"]
    start_ts_us: int | None  # device clock, from index
    end_ts_us: int | None
    byte_ranges: list[ByteRange]
    source: Literal["index", "carved", "inferred"]
    deleted: bool  # true if not referenced by the live index


class FrameRef(_Frozen):
    frame_id: str  # FIX-3: content id of (image_id, offset, payload_sha256) —
    # unique per physical frame; see pramaan_core.ids.frame_id. NOT simply
    # sha256(payload)[:24] (that collapses distinct frames sharing identical
    # payload bytes onto one id) — use payload_sha256 below for a pure
    # payload-integrity check.
    image_id: str
    channel: int | None
    stream: str | None
    codec: Literal["h264", "h265"]
    frame_type: Literal["I", "P", "B", "SPS", "PPS", "VPS", "SEI", "other"]
    header_offset: int | None
    payload_offset: int
    payload_len: int
    ts_header_us: int | None  # device clock from the vendor frame header
    ts_index_us: int | None  # device clock implied by the index
    width: int | None
    height: int | None
    source: Literal["index", "carved", "inferred"]
    recording_id: str | None
    deleted: bool
    # FIX-3, additive per this file's own "change only additively" rule:
    # full sha256 hex of the payload bytes, kept separate from frame_id so
    # payload-integrity checks (e.g. the "prove-it" hex view) have a field
    # that *is* purely a hash of the bytes. Optional/None only for rows
    # written before this field existed or by a caller that hasn't been
    # updated yet — every producer under packages/core, packages/formats,
    # packages/recovery now always sets it.
    payload_sha256: str | None = None


class LogEvent(_Frozen):
    id: str
    image_id: str
    ts_device_us: int
    kind: Literal[
        "login",
        "logout",
        "playback",
        "export",
        "hdd_format",
        "time_change",
        "config_change",
        "power_on",
        "other",
    ]
    user: str | None
    channel: int | None
    details: dict[str, Any]  # e.g. {"old_ts_us": ..., "new_ts_us": ...}
    offset: int  # where on disk the record lives


class DeletionFinding(_Frozen):
    id: str
    image_id: str
    channel: int | None
    start_ts_us: int  # device clock
    end_ts_us: int
    method: Literal["format", "expiry", "overwrite", "unknown"]
    actor: str | None
    action_ts_us: int | None
    frames_recovered: int
    bytes_recovered: int
    confidence: float
    reasons: list[str]  # deterministic sentences, each citing offsets/log ids
    evidence_refs: list[str]  # frame_ids / log event ids / byte ranges


class InferredField(_Frozen):
    name: Literal["magic", "channel", "timestamp", "length", "sequence", "flags", "unknown"]
    offset: int
    width: int
    endian: Literal["le", "be"]
    unit: Literal["s", "ms", "us", "none"] = "none"
    confidence: float
    support: int


class InferredLayout(_Frozen):
    id: str
    image_id: str
    header_len: int
    magic: str | None  # hex
    fields: list[InferredField]
    codec: Literal["h264", "h265"]
    confirmed_by: str | None  # examiner who confirmed; None = unconfirmed


# --- AI / timeline contracts (docs/03-AI-TIMELINE.md §3) --------------------
# Owned by the AI workstream; kept in this file so there is one import path
# for every downstream consumer.


class ClockObservation(_Frozen):
    id: str
    image_id: str
    channel: int | None
    source: Literal["seizure", "log_time_change", "osd", "header", "index", "examiner"]
    device_ts_us: int  # device clock value at the observation
    reference_ts_us: int | None  # true time if known (seizure, examiner)
    offset_us: int  # device − true (positive = device ahead)
    weight: float
    details: dict[str, Any]


class ClockSegment(_Frozen):
    from_device_us: int | None
    to_device_us: int | None
    offset_us: int


class ClockModel(_Frozen):
    id: str
    image_id: str
    channel: int | None  # None = whole device
    segments: list[ClockSegment]  # piecewise-constant offsets
    osd_offset_us: int | None  # camera OSD vs device clock (median)
    confidence: float
    residual_ms: float
    method: str  # human-readable summary
    overridden_by: str | None  # examiner id if manually set


class MotionSegment(_Frozen):
    id: str
    image_id: str
    channel: int
    start_norm_us: int
    end_norm_us: int
    peak_score: float
    frames: int


class Detection(_Frozen):
    id: str
    frame_id: str
    cls: Literal["person", "vehicle", "two_wheeler", "other"]
    score: float
    bbox: tuple[float, float, float, float]  # normalised x, y, w, h
    model: str
    derived_from: str  # proxy file hash
