"""Round-trip tests for pramaan_core.models.

Every model in docs/01-FORENSIC-CORE.md §3.1 / docs/03-AI-TIMELINE.md §3
must: survive model_dump(mode="json") -> model_validate() unchanged, reject
unknown fields (extra="forbid"), and reject mutation after construction
(frozen=True).
"""

from __future__ import annotations

from typing import Any

import pytest
from pramaan_core.models import (
    ByteRange,
    ClockModel,
    ClockObservation,
    ClockSegment,
    DeletionFinding,
    Detection,
    EvidenceImage,
    FrameRef,
    InferredField,
    InferredLayout,
    LogEvent,
    MotionSegment,
    Provenance,
    Recording,
    VendorMatch,
)
from pydantic import ValidationError

IMG = "img_" + "a" * 16

SAMPLES: dict[type, dict[str, Any]] = {
    Provenance: dict(
        parent_sha256="a" * 64,
        tool="pramaan",
        tool_version="0.1.0",
        step="recovery.carve_annexb",
        params={"z": 1, "a": 2},
        created_utc="2026-01-01T00:00:00Z",
    ),
    ByteRange: dict(offset=0x200, length=4096),
    EvidenceImage: dict(
        id=IMG,
        path="/tmp/x.raw",
        format="raw",
        size_bytes=1024,
        sha256="a" * 64,
        md5="b" * 32,
        acquired_utc="2026-01-01T00:00:00Z",
        verified=True,
    ),
    VendorMatch: dict(
        family="hiksim",
        display_name="Hikvision-like (synthetic)",
        platform="hikvision",
        tier="A",
        confidence=0.9,
        evidence=["signature HIKVISION@HANGZHOU at 0x210"],
        model="DS-1",
        serial="SN1",
        fs_version=None,
    ),
    Recording: dict(
        id="rec_" + "a" * 16,
        image_id=IMG,
        channel=1,
        stream="main",
        start_ts_us=0,
        end_ts_us=1000,
        byte_ranges=[ByteRange(offset=0, length=10)],
        source="index",
        deleted=False,
    ),
    FrameRef: dict(
        frame_id="f" * 24,
        image_id=IMG,
        channel=1,
        stream="main",
        codec="h264",
        frame_type="I",
        header_offset=0,
        payload_offset=40,
        payload_len=100,
        ts_header_us=0,
        ts_index_us=0,
        width=1920,
        height=1080,
        source="index",
        recording_id="rec_" + "a" * 16,
        deleted=False,
    ),
    LogEvent: dict(
        id="log_1",
        image_id=IMG,
        ts_device_us=0,
        kind="login",
        user="admin",
        channel=None,
        details={"ip": "1.2.3.4"},
        offset=0x1000,
    ),
    DeletionFinding: dict(
        id="del_1",
        image_id=IMG,
        channel=1,
        start_ts_us=0,
        end_ts_us=1000,
        method="format",
        actor="admin",
        action_ts_us=500,
        frames_recovered=10,
        bytes_recovered=1000,
        confidence=0.8,
        reasons=["formatted at t"],
        evidence_refs=["f1"],
    ),
    InferredField: dict(
        name="timestamp", offset=8, width=4, endian="le", unit="s", confidence=0.7, support=12
    ),
    InferredLayout: dict(
        id="layout_1",
        image_id=IMG,
        header_len=32,
        magic="deadbeef",
        fields=[
            InferredField(name="magic", offset=0, width=4, endian="le", confidence=1.0, support=1)
        ],
        codec="h264",
        confirmed_by=None,
    ),
    ClockObservation: dict(
        id="obs_1",
        image_id=IMG,
        channel=1,
        source="seizure",
        device_ts_us=0,
        reference_ts_us=0,
        offset_us=0,
        weight=1.0,
        details={},
    ),
    ClockSegment: dict(from_device_us=None, to_device_us=None, offset_us=0),
    ClockModel: dict(
        id="clock_1",
        image_id=IMG,
        channel=None,
        segments=[ClockSegment(from_device_us=None, to_device_us=None, offset_us=0)],
        osd_offset_us=None,
        confidence=0.5,
        residual_ms=10.0,
        method="seizure+log",
        overridden_by=None,
    ),
    MotionSegment: dict(
        id="m_1", image_id=IMG, channel=1, start_norm_us=0, end_norm_us=1000, peak_score=0.9,
        frames=30,
    ),
    Detection: dict(
        id="d_1",
        frame_id="f" * 24,
        cls="person",
        score=0.9,
        bbox=(0.1, 0.2, 0.3, 0.4),
        model="yolo",
        derived_from="proxyhash",
    ),
}


@pytest.mark.parametrize("model_cls", list(SAMPLES), ids=[c.__name__ for c in SAMPLES])
def test_round_trip(model_cls: type) -> None:
    instance = model_cls(**SAMPLES[model_cls])
    dumped = instance.model_dump(mode="json")
    restored = model_cls.model_validate(dumped)
    assert restored == instance


@pytest.mark.parametrize("model_cls", list(SAMPLES), ids=[c.__name__ for c in SAMPLES])
def test_frozen(model_cls: type) -> None:
    instance = model_cls(**SAMPLES[model_cls])
    field_name = next(iter(SAMPLES[model_cls]))
    with pytest.raises(ValidationError):
        setattr(instance, field_name, getattr(instance, field_name))


@pytest.mark.parametrize("model_cls", list(SAMPLES), ids=[c.__name__ for c in SAMPLES])
def test_rejects_unknown_field(model_cls: type) -> None:
    payload = dict(SAMPLES[model_cls])
    payload["__bogus__"] = "x"
    with pytest.raises(ValidationError):
        model_cls(**payload)
