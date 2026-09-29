"""API-only response/request models (not shared with other workstreams).

Models that already exist in ``pramaan_core.models`` (``EvidenceImage``,
``Recording``, ``FrameRef``, ``VendorMatch``, ``LogEvent``,
``DeletionFinding``, ``InferredLayout``, ``ClockModel``, ``MotionSegment``,
``Detection``) are reused directly in route signatures instead of being
redefined here — see docs/progress/W0.2.md "API summary".

These are request/response DTOs for concepts that only exist at the API
boundary (cases, jobs, reports, exports, custody entries, search, health).
They are plain (non-frozen) Pydantic models since they cross the wire, not
the forensic content-hash boundary.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_number: str
    title: str
    fir_reference: str | None
    lab: str | None
    status: Literal["open", "closed", "archived"]
    created_utc: str
    updated_utc: str


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_number: str
    title: str
    fir_reference: str | None = None
    lab: str | None = None


class CasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    fir_reference: str | None = None
    lab: str | None = None
    status: Literal["open", "closed", "archived"] | None = None


class SwgdeIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seized_at_local: str
    dvr_displayed_time: str
    reference_time: str
    reference_source: str
    timezone: str
    make_model_label: str | None = None
    serial_label: str | None = None
    write_blocker: str | None = None
    notes: str | None = None


class EvidenceRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    label: str
    intake: SwgdeIntake


class FsEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_utc: str | None
    looks_like_image: bool


class JobStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pending", "running", "done", "failed", "skipped"]
    pct: float
    message: str | None = None


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_id: str
    evidence_id: str | None
    kind: Literal["scan", "verify", "report", "export"]
    status: Literal["queued", "running", "done", "failed"]
    stages: list[JobStage]
    pct: float
    created_utc: str
    updated_utc: str
    log_lines: list[str]


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[str] | None = None
    options: dict[str, Any] = {}


class ReportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_id: str
    created_utc: str
    report_sha256: str
    examiner: str
    pdf_path: str
    certificate_path: str
    manifest_path: str


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_thumbnails: bool = True


class ExportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_id: str
    recording_id: str | None
    channel: int | None
    from_norm_us: int | None
    to_norm_us: int | None
    created_utc: str
    examiner: str
    file_path: str
    signature_path: str
    manifest_sha256: str


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_id: str | None = None
    channel: int | None = None
    from_norm_us: int | None = None
    to_norm_us: int | None = None


class ExportVerifyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature_valid: bool
    manifest: dict[str, Any]
    source_matches_registered_evidence: bool


class ClipRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    recording_id: str
    channel: int
    duration_s: float
    size_bytes: int
    is_derived_proxy: bool
    label: str


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    prev_hash: str | None
    entry_hash: str
    ts_utc: str
    actor: str
    role: str
    action: str
    object_type: str
    object_id: str
    payload_sha256: str | None
    details: dict[str, Any]
    signature: str


class AuditVerifyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    length: int
    head_hash: str | None
    first_bad_seq: int | None


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_id: str
    merkle_root: str
    from_seq: int
    to_seq: int
    ts_utc: str
    backend: Literal["local", "fabric"]
    lab_signature: str


class AnchorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["local", "fabric"] | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["case", "evidence", "recording", "frame", "finding"]
    id: str
    case_id: str
    label: str
    detail: str


class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scanner_backend: Literal["rust", "python"]
    ffmpeg: bool
    pyewf: bool
    weasyprint: bool
    fabric: bool
    llm_enabled: bool
    stub_mode: bool


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class Me(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    role: Literal["examiner", "reviewer", "admin"]
    display_name: str


class Page(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_cursor: str | None


class InferredLayoutConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class HexView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str
    offset: int
    before: int
    after: int
    bytes_b64: str
    annotations: list[dict[str, Any]]
    payload_sha256_recomputed: str
    payload_sha256_stored: str
    matches: bool
