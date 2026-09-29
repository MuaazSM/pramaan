"""Builds the demo case CR-2026-0412 (docs/04-FRONTEND.md §6, docs/PROMPTBOOK.md W0.3).

Everything here is derived from fixed constants and ``random.Random(SEED)``
— never ``datetime.now()`` / ``random`` module-level state / any other
wall-clock or unseeded source — so ``build()`` is byte-for-byte
reproducible (CLAUDE.md rule 5). All hashes, hex bytes, and byte offsets are
**fabricated** (derived from descriptive strings, not real files) — this is
synthetic fixture data for the frontend to build against, not a claim about
any real vendor disk (CLAUDE.md rule 7).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from pramaan_core.ids import content_hash, content_id
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
    Recording,
    VendorMatch,
)

from pramaan_api.schemas import (
    Anchor,
    AuditEntry,
    Case,
    ClipRecord,
    ExportRecord,
    Job,
    JobStage,
    ReportRecord,
)

SEED = 20260412
CASE_ID = "case_cr20260412"
CASE_NUMBER = "CR-2026-0412"
CASE_TITLE = "Shopfront burglary, Andheri"


class ChannelInfo(TypedDict):
    channel: int
    label: str
    color_token: str


CHANNELS: list[ChannelInfo] = [
    {"channel": 1, "label": "CH1 Gate", "color_token": "--ch-1"},
    {"channel": 2, "label": "CH2 Shopfront", "color_token": "--ch-2"},
    {"channel": 3, "label": "CH3 Counter", "color_token": "--ch-3"},
    {"channel": 4, "label": "CH4 Rear lane", "color_token": "--ch-4"},
]

# Fixed "wall clock" for created_utc-style fields. Not derived from now().
FIXED_CREATED_UTC = "2026-03-12T18:05:00.000000Z"

# Device-clock epoch (naive-of-timezone microsecond counter; header/index
# timestamps in the real format are device-local, arbitrary epoch is fine).
_DEVICE_BASE = datetime(2026, 3, 10, 0, 0, 0, tzinfo=UTC)


def _us(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000)


def _fake_sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fake_md5(label: str) -> str:
    return hashlib.md5(label.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass
class FixtureData:
    case: Case
    channels: list[ChannelInfo]
    evidence: dict[str, EvidenceImage]
    vendor_matches: dict[str, list[VendorMatch]]
    recordings: list[Recording]
    frames: list[FrameRef]
    clips: list[ClipRecord]
    log_events: list[LogEvent]
    deletion_findings: list[DeletionFinding]
    inferred_layouts: dict[str, InferredLayout]
    clock_observations: list[ClockObservation]
    clock_models: list[ClockModel]
    motion_segments: list[MotionSegment]
    detections: list[Detection]
    jobs: dict[str, Job]
    reports: list[ReportRecord]
    exports: list[ExportRecord]
    anchors: list[Anchor]
    audit_log: list[AuditEntry] = field(default_factory=list)


def build() -> FixtureData:
    rng = random.Random(SEED)

    case = Case(
        id=CASE_ID,
        case_number=CASE_NUMBER,
        title=CASE_TITLE,
        fir_reference="FIR-0412/2026",
        lab="Regional FSL, Mumbai",
        status="open",
        created_utc=FIXED_CREATED_UTC,
        updated_utc=FIXED_CREATED_UTC,
    )

    image_a, image_b, vendor_matches = _build_evidence()
    recordings, deletion_window = _build_recordings(rng, image_a.id)
    frames = _build_frames(recordings)
    clips = _build_clips(recordings)
    log_events, time_change_ts, format_ts = _build_log_events(image_a.id, deletion_window)
    deletion_findings = _build_deletion_findings(image_a.id, deletion_window, frames, log_events)
    inferred_layouts = _build_inferred_layouts(image_b.id)
    clock_observations, clock_models = _build_clocks(image_a.id, time_change_ts)
    motion_segments, detections = _build_motion(rng, image_a.id, recordings)
    jobs = _build_jobs(image_a.id)
    reports = _build_reports(case.id)
    exports = _build_exports(case.id, recordings)
    anchors = _build_anchors(case.id)

    data = FixtureData(
        case=case,
        channels=CHANNELS,
        evidence={image_a.id: image_a, image_b.id: image_b},
        vendor_matches=vendor_matches,
        recordings=recordings,
        frames=frames,
        clips=clips,
        log_events=log_events,
        deletion_findings=deletion_findings,
        inferred_layouts=inferred_layouts,
        clock_observations=clock_observations,
        clock_models=clock_models,
        motion_segments=motion_segments,
        detections=detections,
        jobs=jobs,
        reports=reports,
        exports=exports,
        anchors=anchors,
    )
    data.audit_log = _build_audit_log(data)
    return data


def _build_evidence() -> tuple[EvidenceImage, EvidenceImage, dict[str, list[VendorMatch]]]:
    path_a = "/evidence/hiksim_format.img"
    sha_a = _fake_sha256(path_a)
    image_a = EvidenceImage(
        id=content_id("img", {"path": path_a, "sha256": sha_a}),
        path=path_a,
        format="raw",
        size_bytes=2_000_398_934_016,  # ~1.82 TiB, deterministic literal
        sha256=sha_a,
        md5=_fake_md5(path_a),
        acquired_utc="2026-03-12T17:10:00.000000Z",
        verified=True,
    )
    path_b = "/evidence/gensim_unknown.img"
    sha_b = _fake_sha256(path_b)
    image_b = EvidenceImage(
        id=content_id("img", {"path": path_b, "sha256": sha_b}),
        path=path_b,
        format="raw",
        size_bytes=500_105_984_000,
        sha256=sha_b,
        md5=_fake_md5(path_b),
        acquired_utc="2026-03-12T17:40:00.000000Z",
        verified=True,
    )
    vendor_matches = {
        image_a.id: [
            VendorMatch(
                family="hiksim",
                display_name="Hikvision-like (synthetic)",
                platform="hikvision",
                tier="A",
                confidence=0.97,
                evidence=[
                    "signature HIKVISION@HANGZHOU at 0x210",
                    "index table checksum valid",
                ],
                model="DS-7208HUHI-K2",
                serial="SYN-HIK-0412",
                fs_version="v4.0",
            )
        ],
        image_b.id: [
            VendorMatch(
                family="gensim",
                display_name="Unrecognised vendor (synthetic)",
                platform=None,
                tier="B",
                confidence=0.41,
                evidence=["no known signature matched", "periodic 512-byte-aligned headers found"],
                model=None,
                serial=None,
                fs_version=None,
            )
        ],
    }
    return image_a, image_b, vendor_matches


def _build_recordings(
    rng: random.Random, image_id: str
) -> tuple[list[Recording], tuple[int, int]]:
    """60 recordings: 4 channels x 15 four-hour slices over 60h.

    A 13h "deletion window" (2026-03-10T20:00 to 2026-03-11T09:00, device
    clock) is carved out below (§ log events / deletion findings): any
    recording overlapping it is marked ``deleted=True, source="carved"``.
    """
    window_start = _us(_DEVICE_BASE + timedelta(hours=20))
    window_end = _us(_DEVICE_BASE + timedelta(hours=33))
    recordings: list[Recording] = []
    bitrate_bps = 4_000_000  # 4 Mbps, fabricated constant for byte-size math
    for ch_info in CHANNELS:
        channel = ch_info["channel"]
        running_offset = channel * 10_000_000_000  # separate byte space per channel
        for i in range(15):
            start_dt = _DEVICE_BASE + timedelta(hours=4 * i)
            end_dt = start_dt + timedelta(hours=4)
            start_us = _us(start_dt)
            end_us = _us(end_dt)
            duration_s = 4 * 3600
            length_bytes = (bitrate_bps // 8) * duration_s
            overlaps_deletion = start_us < window_end and end_us > window_start
            stream = "sub" if i % 4 == 3 else "main"
            source = "carved" if overlaps_deletion else "index"
            byte_range_offset = running_offset
            running_offset += length_bytes + 4096
            rec_key = {
                "image_id": image_id,
                "channel": channel,
                "start": start_us,
                "offset": byte_range_offset,
            }
            rec_id = content_id("rec", rec_key)
            recordings.append(
                Recording(
                    id=rec_id,
                    image_id=image_id,
                    channel=channel,
                    stream=stream,
                    start_ts_us=start_us,
                    end_ts_us=end_us,
                    byte_ranges=[ByteRange(offset=byte_range_offset, length=length_bytes)],
                    source=source,
                    deleted=overlaps_deletion,
                )
            )
    return recordings, (window_start, window_end)


def _build_frames(recordings: list[Recording]) -> list[FrameRef]:
    frames: list[FrameRef] = []
    for rec in recordings:
        byte_range = rec.byte_ranges[0]
        step_us = 2_000_000  # one sampled frame every 2s of the recording, 3 samples
        for i, frame_type in enumerate(("I", "P", "P")):
            ts = (rec.start_ts_us or 0) + i * step_us
            payload_offset = byte_range.offset + i * 65536
            payload_len = 65536 if frame_type == "I" else 8192
            frame_id = content_id(
                "frm",
                {
                    "recording_id": rec.id,
                    "index": i,
                    "payload_offset": payload_offset,
                    "payload_len": payload_len,
                },
                length=24,
            )
            frames.append(
                FrameRef(
                    frame_id=frame_id,
                    image_id=rec.image_id,
                    channel=rec.channel,
                    stream=rec.stream,
                    codec="h264",
                    frame_type=frame_type,
                    header_offset=payload_offset - 32,
                    payload_offset=payload_offset,
                    payload_len=payload_len,
                    ts_header_us=ts,
                    ts_index_us=ts,
                    width=1920,
                    height=1080,
                    source=rec.source,
                    recording_id=rec.id,
                    deleted=rec.deleted,
                )
            )
    return frames


def _build_clips(recordings: list[Recording]) -> list[ClipRecord]:
    clips: list[ClipRecord] = []
    for rec in recordings:
        byte_range = rec.byte_ranges[0]
        clips.append(
            ClipRecord(
                id=content_id("clip", {"recording_id": rec.id}),
                recording_id=rec.id,
                channel=rec.channel,
                duration_s=((rec.end_ts_us or 0) - (rec.start_ts_us or 0)) / 1_000_000,
                size_bytes=byte_range.length,
                is_derived_proxy=True,
                label=f"CH{rec.channel} stream-copied proxy (fixture placeholder)",
            )
        )
    return clips


def _build_log_events(
    image_id: str, deletion_window: tuple[int, int]
) -> tuple[list[LogEvent], int, int]:
    window_start, window_end = deletion_window
    events: list[LogEvent] = []

    # Clock-change marker: device clock set back 1h at 02:00 device time,
    # 2026-03-11 (docs/03-AI-TIMELINE.md §4 example).
    time_change_ts = _us(_DEVICE_BASE + timedelta(hours=26))  # 2026-03-11T02:00
    old_ts = time_change_ts
    new_ts = time_change_ts - 3_600_000_000
    time_change_key = {"image_id": image_id, "kind": "time_change", "ts": time_change_ts}
    events.append(
        LogEvent(
            id=content_id("log", time_change_key),
            image_id=image_id,
            ts_device_us=time_change_ts,
            kind="time_change",
            user=None,
            channel=None,
            details={"old_ts_us": old_ts, "new_ts_us": new_ts, "reason": "manual clock adjustment"},
            offset=0x4A200,
        )
    )

    # Format deletion, actor admin, at the end of the deletion window.
    format_ts = window_end
    events.append(
        LogEvent(
            id=content_id("log", {"image_id": image_id, "kind": "hdd_format", "ts": format_ts}),
            image_id=image_id,
            ts_device_us=format_ts,
            kind="hdd_format",
            user="admin",
            channel=None,
            details={"reason": "disk full, formatted by operator"},
            offset=0x51000,
        )
    )

    extra = [
        ("login", "examiner", 0),
        ("power_on", None, 1),
        ("login", "admin", 2),
        ("config_change", "admin", 3),
        ("playback", "examiner", 40),
        ("export", "examiner", 41),
        ("logout", "admin", 42),
        ("logout", "examiner", 55),
    ]
    for kind, user, hour_offset in extra:
        ts = _us(_DEVICE_BASE + timedelta(hours=hour_offset))
        events.append(
            LogEvent(
                id=content_id("log", {"image_id": image_id, "kind": kind, "ts": ts, "user": user}),
                image_id=image_id,
                ts_device_us=ts,
                kind=kind,
                user=user,
                channel=None,
                details={},
                offset=0x1000 * (hour_offset + 1),
            )
        )
    events.sort(key=lambda e: e.ts_device_us)
    return events, time_change_ts, format_ts


def _build_deletion_findings(
    image_id: str,
    deletion_window: tuple[int, int],
    frames: list[FrameRef],
    log_events: list[LogEvent],
) -> list[DeletionFinding]:
    window_start, window_end = deletion_window
    format_event = next(e for e in log_events if e.kind == "hdd_format")
    recovered = [f for f in frames if f.deleted]
    finding = DeletionFinding(
        id=content_id("del", {"image_id": image_id, "window": deletion_window}),
        image_id=image_id,
        channel=None,
        start_ts_us=window_start,
        end_ts_us=window_end,
        method="format",
        actor="admin",
        action_ts_us=format_event.ts_device_us,
        frames_recovered=len(recovered),
        bytes_recovered=sum(f.payload_len for f in recovered),
        confidence=0.93,
        reasons=[
            "hdd_format log event by 'admin' at offset 0x51000 immediately precedes the gap",
            "carved frames recovered from unallocated space inside the gap on all 4 channels",
            "index has no live recording entries covering this window",
        ],
        evidence_refs=[format_event.id, *[f.frame_id for f in recovered[:5]]],
    )
    return [finding]


def _build_inferred_layouts(image_b_id: str) -> dict[str, InferredLayout]:
    layout = InferredLayout(
        id=content_id("layout", {"image_id": image_b_id}),
        image_id=image_b_id,
        header_len=64,
        magic=None,
        fields=[
            InferredField(
                name="magic",
                offset=0,
                width=4,
                endian="le",
                unit="none",
                confidence=0.55,
                support=812,
            ),
            InferredField(
                name="channel",
                offset=4,
                width=1,
                endian="le",
                unit="none",
                confidence=0.71,
                support=812,
            ),
            InferredField(
                name="timestamp",
                offset=8,
                width=4,
                endian="le",
                unit="s",
                confidence=0.63,
                support=780,
            ),
            InferredField(
                name="length",
                offset=12,
                width=4,
                endian="le",
                unit="none",
                confidence=0.88,
                support=812,
            ),
        ],
        codec="h264",
        confirmed_by=None,
    )
    return {layout.id: layout}


def _build_clocks(
    image_id: str, time_change_ts: int
) -> tuple[list[ClockObservation], list[ClockModel]]:
    seizure_offset_us = 5 * 60_000_000 + 12_000_000  # device +5m12s at seizure
    observations = [
        ClockObservation(
            id=content_id("cobs", {"image_id": image_id, "source": "seizure"}),
            image_id=image_id,
            channel=None,
            source="seizure",
            device_ts_us=_us(datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC)),
            reference_ts_us=_us(datetime(2026, 3, 12, 16, 40, 0, tzinfo=UTC)),
            offset_us=seizure_offset_us,
            weight=1.0,
            details={"reference_source": "NTP phone clock"},
        ),
        ClockObservation(
            id=content_id("cobs", {"image_id": image_id, "source": "log_time_change"}),
            image_id=image_id,
            channel=None,
            source="log_time_change",
            device_ts_us=time_change_ts,
            reference_ts_us=None,
            offset_us=seizure_offset_us - 3_600_000_000,
            weight=0.9,
            details={"old_ts_us": time_change_ts, "new_ts_us": time_change_ts - 3_600_000_000},
        ),
    ]

    models: list[ClockModel] = []
    for ch_info in CHANNELS:
        channel = ch_info["channel"]
        osd_offset = 37_000_000 if channel == 2 else 0  # CH2's OSD camera runs +37s fast
        pre_change_offset = seizure_offset_us - 3_600_000_000
        segments = [
            ClockSegment(
                from_device_us=None, to_device_us=time_change_ts, offset_us=pre_change_offset
            ),
            ClockSegment(
                from_device_us=time_change_ts, to_device_us=None, offset_us=seizure_offset_us
            ),
        ]
        summary = "Device +5m12s at seizure; clock set back 1h at 02:00"
        if osd_offset:
            summary += f"; OSD +{osd_offset // 1_000_000}s"
        models.append(
            ClockModel(
                id=content_id("clk", {"image_id": image_id, "channel": channel}),
                image_id=image_id,
                channel=channel,
                segments=segments,
                osd_offset_us=osd_offset or None,
                confidence=0.9 if osd_offset else 0.85,
                residual_ms=180.0,
                method=summary,
                overridden_by=None,
            )
        )
    return observations, models


def _build_motion(
    rng: random.Random, image_id: str, recordings: list[Recording]
) -> tuple[list[MotionSegment], list[Detection]]:
    segments: list[MotionSegment] = []
    non_deleted = [r for r in recordings if not r.deleted]
    for ch_info in CHANNELS:
        channel = ch_info["channel"]
        chan_recs = [r for r in non_deleted if r.channel == channel][:3]
        for rec in chan_recs:
            start = (rec.start_ts_us or 0) + 600_000_000
            end = start + 45_000_000
            segments.append(
                MotionSegment(
                    id=content_id("mot", {"recording_id": rec.id}),
                    image_id=image_id,
                    channel=channel,
                    start_norm_us=start,
                    end_norm_us=end,
                    peak_score=round(3.2 + rng.random() * 2.5, 2),
                    frames=round((end - start) / 1_000_000 * 15),
                )
            )
    detections: list[Detection] = []  # P2, optional — none in the fixture corpus
    return segments, detections


def _build_jobs(image_id: str) -> dict[str, Job]:
    job = Job(
        id=content_id("job", {"image_id": image_id, "kind": "scan"}),
        case_id=CASE_ID,
        evidence_id=image_id,
        kind="scan",
        status="done",
        stages=[
            JobStage(name=name, status="done", pct=100.0)
            for name in (
                "hash_verify",
                "fingerprint",
                "parse_index",
                "infer_layout",
                "carve",
                "frame_index",
                "logs",
                "deletion_verdict",
                "clips",
                "timeline",
                "motion",
            )
        ],
        pct=100.0,
        created_utc="2026-03-12T17:15:00.000000Z",
        updated_utc="2026-03-12T17:52:00.000000Z",
        log_lines=[
            "hash_verify: sha256 + md5 confirmed",
            "fingerprint: hiksim tier A, confidence 0.97",
            "carve: 41,206 recovered frames across 4 channels",
            "deletion_verdict: 1 finding (format by admin)",
            "timeline: 4 clock models built, CH2 OSD +37s",
        ],
    )
    return {job.id: job}


def _build_reports(case_id: str) -> list[ReportRecord]:
    manifest_label = f"{case_id}:report:1"
    return [
        ReportRecord(
            id=content_id("rpt", {"case_id": case_id, "n": 1}),
            case_id=case_id,
            created_utc="2026-03-12T18:00:00.000000Z",
            report_sha256=_fake_sha256(manifest_label),
            examiner="examiner",
            pdf_path=f"cases/{case_id}/reports/report-1.pdf",
            certificate_path=f"cases/{case_id}/reports/certificate-1.pdf",
            manifest_path=f"cases/{case_id}/reports/manifest-1.json",
        )
    ]


def _build_exports(case_id: str, recordings: list[Recording]) -> list[ExportRecord]:
    rec = recordings[0]
    return [
        ExportRecord(
            id=content_id("exp", {"case_id": case_id, "recording_id": rec.id}),
            case_id=case_id,
            recording_id=rec.id,
            channel=rec.channel,
            from_norm_us=rec.start_ts_us,
            to_norm_us=rec.end_ts_us,
            created_utc="2026-03-12T18:02:00.000000Z",
            examiner="examiner",
            file_path=f"cases/{case_id}/exports/export-1.mp4",
            signature_path=f"cases/{case_id}/exports/export-1.mp4.sig",
            manifest_sha256=_fake_sha256(f"{case_id}:export:1"),
        )
    ]


def _build_anchors(case_id: str) -> list[Anchor]:
    return [
        Anchor(
            id=content_id("anc", {"case_id": case_id, "n": 1}),
            case_id=case_id,
            merkle_root=_fake_sha256(f"{case_id}:merkle:1"),
            from_seq=1,
            to_seq=100,
            ts_utc="2026-03-12T18:03:00.000000Z",
            backend="local",
            lab_signature=_fake_sha256(f"{case_id}:lab-sig:1"),
        )
    ]


def _build_audit_log(data: FixtureData) -> list[AuditEntry]:
    """Hash-chained custody log (docs/02-BACKEND.md §8): ``entry_hash =
    sha256(canonical_json(entry))``. ``signature`` here is a fixture
    placeholder derived from ``entry_hash`` — real Ed25519 signing over an
    examiner key is ``packages/custody``'s job (a later task), not W0.3.
    """
    actions: list[tuple[str, str, str, str, str, dict[str, object]]] = []
    # (actor, role, action, object_type, object_id, details)
    actions.append(("examiner", "examiner", "case.created", "case", data.case.id, {}))
    for image in data.evidence.values():
        actions.append(
            ("examiner", "examiner", "evidence.registered", "evidence_image", image.id, {})
        )
        actions.append(
            (
                "examiner",
                "examiner",
                "evidence.verified",
                "evidence_image",
                image.id,
                {"match": True},
            )
        )
    for job in data.jobs.values():
        for stage in job.stages:
            actions.append(("examiner", "examiner", f"stage.{stage.name}.start", "job", job.id, {}))
            actions.append(("examiner", "examiner", f"stage.{stage.name}.done", "job", job.id, {}))
    for finding in data.deletion_findings:
        actions.append(("admin", "admin", "deletion.recorded", "deletion_finding", finding.id, {}))
    for report in data.reports:
        actions.append(("examiner", "examiner", "report.generated", "report", report.id, {}))
    for export in data.exports:
        actions.append(("examiner", "examiner", "export.created", "export", export.id, {}))
    for anchor in data.anchors:
        actions.append(("examiner", "examiner", "anchor.created", "anchor", anchor.id, {}))

    # Pad with alternating login/logout/playback entries to reach ~130.
    pad_actors = (("examiner", "examiner"), ("reviewer", "reviewer"), ("admin", "admin"))
    pad_kinds = ("auth.login", "recordings.viewed", "auth.logout")
    i = 0
    while len(actions) < 128:
        actor, role = pad_actors[i % len(pad_actors)]
        kind = pad_kinds[i % len(pad_kinds)]
        actions.append((actor, role, kind, "session", f"sess_{i:04d}", {}))
        i += 1

    entries: list[AuditEntry] = []
    prev_hash: str | None = None
    base_ts = datetime(2026, 3, 12, 17, 0, 0, tzinfo=UTC)
    for seq, (actor, role, action, object_type, object_id, details) in enumerate(actions, start=1):
        ts_dt = base_ts + timedelta(seconds=15 * seq)
        ts_utc = ts_dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
        payload_sha256 = _fake_sha256(f"{object_type}:{object_id}:{action}")
        unsigned = {
            "seq": seq,
            "prev_hash": prev_hash,
            "ts_utc": ts_utc,
            "actor": actor,
            "role": role,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "payload_sha256": payload_sha256,
            "details": details,
        }
        entry_hash = content_hash(unsigned)
        signature = "sig_fixture_" + content_hash({"entry_hash": entry_hash})[:48]
        entries.append(
            AuditEntry(
                seq=seq,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
                ts_utc=ts_utc,
                actor=actor,
                role=role,
                action=action,
                object_type=object_type,
                object_id=object_id,
                payload_sha256=payload_sha256,
                details=details,
                signature=signature,
            )
        )
        prev_hash = entry_hash
    return entries
