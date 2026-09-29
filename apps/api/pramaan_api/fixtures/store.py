"""Read/query layer over the generated fixture dataset.

Every router imports functions from here instead of touching
``generate.build()`` (or its returned ``FixtureData``) directly, so the
dataset stays a single process-wide singleton (``DATA``) built once,
deterministically, at import time.

A handful of functions ("register_evidence", "create_job", "confirm_layout",
...) mutate the in-memory singleton to make the demo feel interactive
end-to-end; none of it is persisted to disk, and every process restart goes
back to exactly ``generate.build()``'s output.
"""

from __future__ import annotations

import hashlib
import posixpath
from typing import Literal

from pramaan_core.ids import content_hash, content_id
from pramaan_core.models import (
    ClockModel,
    DeletionFinding,
    Detection,
    EvidenceImage,
    FrameRef,
    InferredLayout,
    LogEvent,
    MotionSegment,
    Recording,
    VendorMatch,
)

from pramaan_api.fixtures.generate import ChannelInfo, FixtureData, build
from pramaan_api.pagination import paginate
from pramaan_api.schemas import (
    Anchor,
    AuditEntry,
    AuditVerifyResult,
    Case,
    ClipRecord,
    ExportRecord,
    FsEntry,
    HealthStatus,
    Job,
    JobStage,
    ReportRecord,
    SearchResult,
    SwgdeIntake,
)

DATA: FixtureData = build()


# --- cases -------------------------------------------------------------


def list_cases() -> list[Case]:
    return [DATA.case]


def get_case(case_id: str) -> Case | None:
    return DATA.case if case_id == DATA.case.id else None


def patch_case(
    case_id: str,
    *,
    title: str | None,
    fir_reference: str | None,
    lab: str | None,
    status: str | None,
) -> Case | None:
    if case_id != DATA.case.id:
        return None
    candidate = {"title": title, "fir_reference": fir_reference, "lab": lab, "status": status}
    updates = {k: v for k, v in candidate.items() if v is not None}
    updated = DATA.case.model_copy(update=updates)
    DATA.case = updated
    return updated


# --- evidence ------------------------------------------------------------


def list_evidence(case_id: str) -> list[EvidenceImage]:
    if case_id != DATA.case.id:
        return []
    return list(DATA.evidence.values())


def get_evidence(evidence_id: str) -> EvidenceImage | None:
    return DATA.evidence.get(evidence_id)


def get_vendor_matches(evidence_id: str) -> list[VendorMatch]:
    return DATA.vendor_matches.get(evidence_id, [])


def register_evidence(case_id: str, path: str, label: str, intake: SwgdeIntake) -> EvidenceImage:
    sha = hashlib.sha256(path.encode("utf-8")).hexdigest()
    image = EvidenceImage(
        id=content_id("img", {"path": path, "sha256": sha, "n": len(DATA.evidence)}),
        path=path,
        format="raw",
        size_bytes=0,
        sha256=sha,
        md5=hashlib.md5(path.encode("utf-8"), usedforsecurity=False).hexdigest(),
        acquired_utc=DATA.case.updated_utc,
        verified=False,
    )
    DATA.evidence[image.id] = image
    DATA.vendor_matches[image.id] = []
    return image


# --- inferred layouts ------------------------------------------------------


def get_inferred_layout_for_evidence(evidence_id: str) -> InferredLayout | None:
    for layout in DATA.inferred_layouts.values():
        if layout.image_id == evidence_id:
            return layout
    return None


def get_inferred_layout(layout_id: str) -> InferredLayout | None:
    return DATA.inferred_layouts.get(layout_id)


def confirm_inferred_layout(layout_id: str, examiner: str) -> InferredLayout | None:
    layout = DATA.inferred_layouts.get(layout_id)
    if layout is None:
        return None
    updated = layout.model_copy(update={"confirmed_by": examiner})
    DATA.inferred_layouts[layout_id] = updated
    return updated


# --- recordings / frames ---------------------------------------------------


def list_recordings(
    case_id: str,
    *,
    channel: int | None = None,
    source: str | None = None,
    deleted: bool | None = None,
    frm: int | None = None,
    to: int | None = None,
) -> list[Recording]:
    if case_id != DATA.case.id:
        return []
    out = DATA.recordings
    if channel is not None:
        out = [r for r in out if r.channel == channel]
    if source is not None:
        out = [r for r in out if r.source == source]
    if deleted is not None:
        out = [r for r in out if r.deleted == deleted]
    if frm is not None:
        out = [r for r in out if r.end_ts_us is None or r.end_ts_us >= frm]
    if to is not None:
        out = [r for r in out if r.start_ts_us is None or r.start_ts_us <= to]
    return out


def get_recording(recording_id: str) -> Recording | None:
    return next((r for r in DATA.recordings if r.id == recording_id), None)


def list_frames(
    case_id: str,
    *,
    channel: int | None = None,
    source: str | None = None,
    deleted: bool | None = None,
    frame_type: str | None = None,
    frm: int | None = None,
    to: int | None = None,
) -> list[FrameRef]:
    if case_id != DATA.case.id:
        return []
    out = DATA.frames
    if channel is not None:
        out = [f for f in out if f.channel == channel]
    if source is not None:
        out = [f for f in out if f.source == source]
    if deleted is not None:
        out = [f for f in out if f.deleted == deleted]
    if frame_type is not None:
        out = [f for f in out if f.frame_type == frame_type]
    if frm is not None:
        out = [f for f in out if (f.ts_header_us or 0) >= frm]
    if to is not None:
        out = [f for f in out if (f.ts_header_us or 0) <= to]
    return out


def get_frame(frame_id: str) -> FrameRef | None:
    return next((f for f in DATA.frames if f.frame_id == frame_id), None)


def _synthetic_bytes(seed: str, length: int) -> bytes:
    """Deterministic pseudo-bytes for a fixture region (never real evidence)."""
    out = bytearray()
    counter = 0
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    while len(out) < length:
        out.extend(hashlib.sha256(digest + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:length])


def frame_hex_view(frame: FrameRef, before: int, after: int) -> dict[str, object]:
    start = max(0, frame.payload_offset - before)
    length = (frame.payload_offset - start) + after
    payload = _synthetic_bytes(frame.frame_id, length)
    header_len = frame.payload_offset - start
    payload_only = payload[header_len:]
    recomputed = hashlib.sha256(payload_only).hexdigest()
    annotations = [
        {"name": "vendor_header", "offset": 0, "length": max(header_len, 0)},
        {"name": "start_code", "offset": max(header_len - 4, 0), "length": min(4, header_len)},
        {"name": "payload", "offset": header_len, "length": len(payload_only)},
    ]
    return {
        "offset": start,
        "bytes": payload,
        "annotations": annotations,
        "payload_sha256_recomputed": recomputed,
        "payload_sha256_stored": recomputed,  # fixture: fabricated bytes always match
    }


def frame_thumb_bytes(frame: FrameRef) -> bytes:
    # Minimal valid 1x1 JPEG, reused for every fixture frame — a real
    # decoded-keyframe thumbnail is produced by the real pipeline (recovery).
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300030202020203"
        "0202030303030406040404040408060605070907080808070808090a0c0a09"
        "090b090808080c0a0b0b0c0e0e0e0e0e08090d0f0d0e0e0e0c0dffc0000b080"
        "0010001030100022200ffc4001f0000010501010101010100000000000000"
        "0102030405060708090a0bffc400b5100002010303020403050504040000017"
        "d01020300041105122131410613516107227114328191a1082342b1c11552d1"
        "f02433627282090a161718191a25262728292a3435363738393a4344454647"
        "48494a535455565758595a636465666768696a737475767778797a8283848"
        "5868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b"
        "9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f"
        "2f3f4f5f6f7f8f9faffda0008010100003f00fb"
    )


# --- clips -------------------------------------------------------------


def get_clip(clip_id: str) -> ClipRecord | None:
    return next((c for c in DATA.clips if c.id == clip_id), None)


def clip_bytes(clip: ClipRecord) -> bytes:
    """A small deterministic byte blob standing in for a stream-copied MP4."""
    header = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    body = _synthetic_bytes(clip.id, max(4096 - len(header), 0))
    return header + body


# --- logs / deletions --------------------------------------------------


def list_log_events(case_id: str, *, kind: str | None = None) -> list[LogEvent]:
    if case_id != DATA.case.id:
        return []
    out = DATA.log_events
    if kind is not None:
        out = [e for e in out if e.kind == kind]
    return out


def list_deletions(case_id: str) -> list[DeletionFinding]:
    if case_id != DATA.case.id:
        return []
    return DATA.deletion_findings


# --- timeline / analytics (used by the AI stub routers) --------------------


def list_channels(case_id: str) -> list[ChannelInfo]:
    return DATA.channels if case_id == DATA.case.id else []


def list_clock_models(case_id: str) -> list[ClockModel]:
    return DATA.clock_models if case_id == DATA.case.id else []


def get_clock_model(model_id: str) -> ClockModel | None:
    return next((m for m in DATA.clock_models if m.id == model_id), None)


def override_clock_model(model_id: str, examiner: str) -> ClockModel | None:
    model = get_clock_model(model_id)
    if model is None:
        return None
    updated = model.model_copy(update={"overridden_by": examiner})
    DATA.clock_models = [updated if m.id == model_id else m for m in DATA.clock_models]
    return updated


def list_motion_segments(case_id: str, *, channel: int | None = None) -> list[MotionSegment]:
    if case_id != DATA.case.id:
        return []
    out = DATA.motion_segments
    if channel is not None:
        out = [m for m in out if m.channel == channel]
    return out


def list_detections(case_id: str) -> list[Detection]:
    return DATA.detections if case_id == DATA.case.id else []


# --- jobs ----------------------------------------------------------------


def list_jobs(case_id: str) -> list[Job]:
    return [j for j in DATA.jobs.values() if j.case_id == case_id]


def get_job(job_id: str) -> Job | None:
    return DATA.jobs.get(job_id)


def create_job(
    case_id: str,
    evidence_id: str | None,
    kind: Literal["scan", "verify", "report", "export"],
    stage_names: list[str],
) -> Job:
    job_key = {"case_id": case_id, "evidence_id": evidence_id, "kind": kind, "n": len(DATA.jobs)}
    job = Job(
        id=content_id("job", job_key),
        case_id=case_id,
        evidence_id=evidence_id,
        kind=kind,
        status="queued",
        stages=[JobStage(name=name, status="pending", pct=0.0) for name in stage_names],
        pct=0.0,
        created_utc=DATA.case.updated_utc,
        updated_utc=DATA.case.updated_utc,
        log_lines=[],
    )
    DATA.jobs[job.id] = job
    return job


# --- reports / exports -----------------------------------------------------


def list_reports(case_id: str) -> list[ReportRecord]:
    return [r for r in DATA.reports if r.case_id == case_id]


def get_report(report_id: str) -> ReportRecord | None:
    return next((r for r in DATA.reports if r.id == report_id), None)


def create_report(case_id: str, examiner: str) -> ReportRecord:
    n = len(DATA.reports) + 1
    report = ReportRecord(
        id=content_id("rpt", {"case_id": case_id, "n": n}),
        case_id=case_id,
        created_utc=DATA.case.updated_utc,
        report_sha256=content_hash({"case_id": case_id, "n": n}),
        examiner=examiner,
        pdf_path=f"cases/{case_id}/reports/report-{n}.pdf",
        certificate_path=f"cases/{case_id}/reports/certificate-{n}.pdf",
        manifest_path=f"cases/{case_id}/reports/manifest-{n}.json",
    )
    DATA.reports.append(report)
    return report


def list_exports(case_id: str) -> list[ExportRecord]:
    return [x for x in DATA.exports if x.case_id == case_id]


def get_export(export_id: str) -> ExportRecord | None:
    return next((x for x in DATA.exports if x.id == export_id), None)


def create_export(
    case_id: str,
    examiner: str,
    recording_id: str | None,
    channel: int | None,
    from_us: int | None,
    to_us: int | None,
) -> ExportRecord:
    n = len(DATA.exports) + 1
    export = ExportRecord(
        id=content_id("exp", {"case_id": case_id, "n": n}),
        case_id=case_id,
        recording_id=recording_id,
        channel=channel,
        from_norm_us=from_us,
        to_norm_us=to_us,
        created_utc=DATA.case.updated_utc,
        examiner=examiner,
        file_path=f"cases/{case_id}/exports/export-{n}.mp4",
        signature_path=f"cases/{case_id}/exports/export-{n}.mp4.sig",
        manifest_sha256=content_hash({"case_id": case_id, "n": n}),
    )
    DATA.exports.append(export)
    return export


# --- audit / anchors ---------------------------------------------------


def list_audit(
    case_id: str, *, cursor: str | None, limit: int | None
) -> tuple[list[AuditEntry], str | None]:
    if case_id != DATA.case.id:
        return [], None
    return paginate(DATA.audit_log, cursor, limit)


def verify_chain(entries: list[AuditEntry]) -> AuditVerifyResult:
    """Recompute the hash chain (docs/02-BACKEND.md §8) and report the first
    broken link, if any. Pure function of ``entries`` — used both by
    ``verify_audit`` (against the live fixture dataset) and directly by
    tests (against a hand-tampered copy, without touching global state).
    """
    if not entries:
        return AuditVerifyResult(ok=True, length=0, head_hash=None, first_bad_seq=None)
    prev_hash: str | None = None
    for entry in entries:
        unsigned = {
            "seq": entry.seq,
            "prev_hash": entry.prev_hash,
            "ts_utc": entry.ts_utc,
            "actor": entry.actor,
            "role": entry.role,
            "action": entry.action,
            "object_type": entry.object_type,
            "object_id": entry.object_id,
            "payload_sha256": entry.payload_sha256,
            "details": entry.details,
        }
        expected_hash = content_hash(unsigned)
        if entry.prev_hash != prev_hash or entry.entry_hash != expected_hash:
            return AuditVerifyResult(
                ok=False, length=len(entries), head_hash=None, first_bad_seq=entry.seq
            )
        prev_hash = entry.entry_hash
    return AuditVerifyResult(ok=True, length=len(entries), head_hash=prev_hash, first_bad_seq=None)


def verify_audit(case_id: str) -> AuditVerifyResult:
    if case_id != DATA.case.id:
        return AuditVerifyResult(ok=True, length=0, head_hash=None, first_bad_seq=None)
    return verify_chain(DATA.audit_log)


def list_anchors(case_id: str) -> list[Anchor]:
    return [a for a in DATA.anchors if a.case_id == case_id]


def create_anchor(case_id: str, backend: Literal["local", "fabric"]) -> Anchor:
    n = len(DATA.anchors) + 1
    entries, _ = list_audit(case_id, cursor=None, limit=None)
    from_seq = entries[0].seq if entries else 1
    to_seq = DATA.audit_log[-1].seq if DATA.audit_log else 1
    anchor = Anchor(
        id=content_id("anc", {"case_id": case_id, "n": n}),
        case_id=case_id,
        merkle_root=content_hash({"case_id": case_id, "n": n, "to_seq": to_seq}),
        from_seq=from_seq,
        to_seq=to_seq,
        ts_utc=DATA.case.updated_utc,
        backend=backend,
        lab_signature="sig_fixture_" + content_hash({"anchor": n})[:48],
    )
    DATA.anchors.append(anchor)
    return anchor


# --- search / fs / system ---------------------------------------------------


def search(q: str) -> list[SearchResult]:
    ql = q.strip().lower()
    if not ql:
        return []
    results: list[SearchResult] = []
    if ql in DATA.case.case_number.lower() or ql in DATA.case.title.lower():
        results.append(
            SearchResult(
                kind="case",
                id=DATA.case.id,
                case_id=DATA.case.id,
                label=DATA.case.case_number,
                detail=DATA.case.title,
            )
        )
    for image in DATA.evidence.values():
        if ql in image.path.lower() or ql in image.id.lower():
            results.append(
                SearchResult(
                    kind="evidence",
                    id=image.id,
                    case_id=DATA.case.id,
                    label=image.path,
                    detail=image.format,
                )
            )
    for rec in DATA.recordings:
        if ql in rec.id.lower() or ql == f"ch{rec.channel}":
            results.append(
                SearchResult(
                    kind="recording",
                    id=rec.id,
                    case_id=DATA.case.id,
                    label=f"CH{rec.channel} recording",
                    detail=rec.source,
                )
            )
    for finding in DATA.deletion_findings:
        if ql in finding.method.lower() or (finding.actor and ql in finding.actor.lower()):
            results.append(
                SearchResult(
                    kind="finding",
                    id=finding.id,
                    case_id=DATA.case.id,
                    label=f"{finding.method} deletion",
                    detail=", ".join(finding.reasons[:1]),
                )
            )
    return results[:50]


_ALLOWED_ROOT = "/evidence"


def is_within_evidence_root(path: str) -> bool:
    """True iff ``path`` normalises (symlink-unaware — resolving real
    symlinks needs a real filesystem, which this fixture store doesn't
    have) to somewhere under ``EVIDENCE_ROOTS`` (docs/02-BACKEND.md §11:
    "resolve ... and reject traversal"). Used by both ``fs_browse`` and
    evidence registration so a single check governs both.
    """
    normalized = posixpath.normpath(path or _ALLOWED_ROOT)
    return normalized == _ALLOWED_ROOT or normalized.startswith(_ALLOWED_ROOT + "/")


def fs_browse(path: str) -> list[FsEntry]:
    if not is_within_evidence_root(path):
        return []
    return [
        FsEntry(
            name=image.path.rsplit("/", 1)[-1],
            path=image.path,
            is_dir=False,
            size_bytes=image.size_bytes,
            modified_utc=image.acquired_utc,
            looks_like_image=True,
        )
        for image in DATA.evidence.values()
    ]


def system_health(*, llm_enabled: bool, stub_mode: bool) -> HealthStatus:
    return HealthStatus(
        scanner_backend="python",
        ffmpeg=True,
        pyewf=False,
        weasyprint=False,
        fabric=False,
        llm_enabled=llm_enabled,
        stub_mode=stub_mode,
    )
