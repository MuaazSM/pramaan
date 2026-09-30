"""Real (non-fixture) report generation (task B3, docs/02-BACKEND.md §9).

Gathers a case's real state into ``pramaan_reporting.ManifestInputs``,
builds the signed report/certificate PDFs via ``pramaan_reporting``, persists
them under ``<case_dir>/reports/<report_id>/``, appends the
``report.generated`` audit entry (docs §8), and anchors the case (docs §8:
"Anchor on report generation").

Determinism note (CLAUDE.md rule 5, docs §9 step 1 — "identical across
re-runs"): ``build_manifest``/``report_sha256`` are pure functions of the
gathered ``ManifestInputs`` (unit-tested directly in
``tests/backend/test_reports_real.py``); a *live* case's custody chain
necessarily grows by exactly the ``report.generated`` + ``anchor.created``
entries this same call appends (docs §8 requires both to be audited), so two
back-to-back mutating ``POST`` calls on the same case will legitimately
produce two *different* ``report_sha256`` values (state genuinely changed:
one more report + one more anchor now exist) — determinism is verified at
the level the PRD actually cares about: re-reading an already-generated
report's manifest (``GET /reports/{rid}/manifest``, read-only) always
returns the same hash, and rebuilding the manifest from an unchanged
snapshot of gathered inputs always produces byte-identical output.
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
from typing import Any

from pramaan_core.timeutil import utc_now_iso
from pramaan_reporting import ManifestInputs, build_report
from pramaan_worker.runner import STAGE_NAMES

from pramaan_api.errors import not_found
from pramaan_api.real import appdb
from pramaan_api.real import pipeline_store as pstore
from pramaan_api.real import store as real_store
from pramaan_api.real.paths import case_dir, keys_dir
from pramaan_api.schemas import ReportRecord
from pramaan_api.security import User
from pramaan_api.settings import Settings


def _tool_version() -> str:
    try:
        return metadata.version("pramaan-core")
    except metadata.PackageNotFoundError:
        return "0.0.0+unknown"


def _representative_thumbnails(
    data_dir: str, case_id: str, deletion_findings: list[dict[str, Any]], *, limit: int = 6
) -> list[dict[str, Any]]:
    """Best-effort representative recovered-frame thumbnails for the report
    body (docs §9 step 2: "recovered footage ... with representative
    thumbnails"). Never fails report generation — a frame that can't be
    thumbnailed (e.g. no leading keyframe reachable) is silently skipped.
    """
    import base64

    frame_ids: list[str] = []
    for finding in deletion_findings:
        for ref in finding.get("evidence_refs", []):
            if isinstance(ref, str) and ref.startswith("frm_"):
                frame_ids.append(ref)
    if not frame_ids:
        # Fall back to any carved/recovered frame in the index.
        try:
            frames = pstore.list_frames(data_dir, case_id, source="carved", limit=limit)
            frame_ids = [f.frame_id for f in frames]
        except Exception:  # pragma: no cover - defensive, thumbnails are best-effort
            frame_ids = []

    out: list[dict[str, Any]] = []
    for fid in sorted(set(frame_ids))[:limit]:
        try:
            data = pstore.frame_thumbnail_bytes(data_dir, fid)
        except Exception:  # pragma: no cover - defensive, thumbnails are best-effort
            data = None
        if not data:
            continue
        frame = pstore.get_frame(data_dir, fid)
        out.append(
            {
                "frame_id": fid,
                "channel": frame.channel if frame is not None else None,
                "image_b64": base64.b64encode(data).decode("ascii"),
            }
        )
    return out


def _intake_kind_by_image(data_dir: str, case_id: str) -> dict[str, str]:
    """Per-image intake path — ``"acquired_by_pramaan"`` if a
    ``Provenance`` record with step ``"acquire.acquire"`` is on file for
    that image (``pramaan_core.acquire.acquire`` — a write-blocked,
    read-only duplication), else ``"registered_existing"`` (
    ``pramaan_core.acquire.register_existing`` — the image already existed
    on disk and was only hashed/registered, never duplicated). The BSA
    certificate's "how the record was produced" wording (item 5,
    docs/progress/FIX-10.md, CLAUDE.md rule 7) must never claim an
    acquisition Pramaan did not perform, so this is read directly off the
    already-existing, nullable ``evidence_images.provenance`` column rather
    than assumed — no ``pramaan_api.real.store``/schema change needed, and
    every evidence image registered through the currently-exposed
    ``register_evidence`` API path (the only one wired to a route today)
    correctly comes back ``"registered_existing"``.
    """
    guarded = appdb.case_db(data_dir, case_id)
    rows = guarded.conn.execute(
        "SELECT id, provenance FROM evidence_images WHERE case_id = ?", (case_id,)
    ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        raw = row["provenance"]
        step = None
        if raw:
            try:
                step = json.loads(raw).get("step")
            except (ValueError, AttributeError):
                step = None
        out[row["id"]] = (
            "acquired_by_pramaan" if step == "acquire.acquire" else "registered_existing"
        )
    return out


def _gather_manifest_inputs(data_dir: str, case_id: str, actor: User) -> ManifestInputs:
    case = real_store.get_case(data_dir, case_id)
    if case is None:
        raise not_found("case", case_id)
    evidence = real_store.list_evidence(data_dir, case_id)
    intake_kind = _intake_kind_by_image(data_dir, case_id)

    vendor_matches: dict[str, list[dict[str, Any]]] = {}
    clock_observations: list[dict[str, Any]] = []
    for image in evidence:
        vendor_matches[image.id] = [
            m.model_dump() for m in pstore.list_vendor_matches(data_dir, image.id)
        ]
        clock_observations.extend(
            obs.model_dump()
            for obs in real_store.list_clock_observations(data_dir, case_id, image.id)
        )

    recordings = [r.model_dump() for r in pstore.list_recordings(data_dir, case_id)]
    deletion_findings = [d.model_dump() for d in pstore.list_deletions(data_dir, case_id)]
    log_events = [e.model_dump() for e in pstore.list_log_events(data_dir, case_id)]
    anchors = [a.model_dump() for a in real_store.list_anchors(data_dir, case_id)]
    audit_verify = real_store.verify_audit(data_dir, case_id)

    return ManifestInputs(
        case={
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "fir_reference": case.fir_reference,
            "lab": case.lab,
            "status": case.status,
        },
        examiner={"username": actor.username, "role": actor.role},
        evidence=[
            {**e.model_dump(), "intake_kind": intake_kind.get(e.id, "registered_existing")}
            for e in evidence
        ],
        vendor_matches=vendor_matches,
        recordings=recordings,
        deletion_findings=deletion_findings,
        clock_observations=clock_observations,
        log_events=log_events,
        custody={"head_hash": audit_verify.head_hash, "length": audit_verify.length},
        anchors=anchors,
        methods={
            "tool": "pramaan",
            "tool_version": _tool_version(),
            "stage_order": list(STAGE_NAMES),
        },
    )


def _report_dir(data_dir: str, case_id: str, report_id: str) -> Path:
    return case_dir(data_dir, case_id) / "reports" / report_id


def create_report(settings: Settings, actor: User, case_id: str) -> ReportRecord:
    data_dir = settings.data_dir
    inputs = _gather_manifest_inputs(data_dir, case_id, actor)
    thumbnails = _representative_thumbnails(data_dir, case_id, inputs.deletion_findings)
    generated_utc = utc_now_iso()

    artifacts = build_report(
        inputs, keys_dir=keys_dir(data_dir), generated_utc=generated_utc, thumbnails=thumbnails
    )

    rdir = _report_dir(data_dir, case_id, artifacts.report_id)
    rdir.mkdir(parents=True, exist_ok=True)
    manifest_path = rdir / "manifest.json"
    pdf_path = rdir / "report.pdf"
    certificate_path = rdir / "certificate.pdf"
    envelope_path = rdir / "envelope.json"

    manifest_path.write_bytes(artifacts.manifest_json)
    pdf_path.write_bytes(artifacts.pdf_bytes)
    certificate_path.write_bytes(artifacts.certificate_pdf_bytes)
    envelope_path.write_text(
        json.dumps(
            {
                "report_id": artifacts.report_id,
                "case_id": case_id,
                "report_sha256": artifacts.report_sha256,
                "generated_utc": generated_utc,
                "generated_by": actor.username,
                "pdf_backend": artifacts.pdf_backend,
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        guarded.conn.execute(
            "INSERT OR REPLACE INTO reports "
            "(id, case_id, report_sha256, manifest_path, pdf_path, created_utc, created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                artifacts.report_id,
                case_id,
                artifacts.report_sha256,
                str(manifest_path),
                str(pdf_path),
                generated_utc,
                actor.username,
            ),
        )
        guarded.conn.commit()

    real_store.append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="report.generated",
        object_type="report",
        object_id=artifacts.report_id,
        payload_sha256=artifacts.report_sha256,
        details={"pdf_backend": artifacts.pdf_backend},
    )

    # docs/02-BACKEND.md §8: "Anchor on report generation and on demand."
    real_store.create_anchor(data_dir, actor, case_id, settings.anchor_backend)

    return ReportRecord(
        id=artifacts.report_id,
        case_id=case_id,
        created_utc=generated_utc,
        report_sha256=artifacts.report_sha256,
        examiner=actor.username,
        pdf_path=str(pdf_path),
        certificate_path=str(certificate_path),
        manifest_path=str(manifest_path),
    )


def _row_to_report(row: Any) -> ReportRecord:
    pdf_path = row["pdf_path"] or ""
    certificate_path = str(Path(pdf_path).with_name("certificate.pdf")) if pdf_path else ""
    return ReportRecord(
        id=row["id"],
        case_id=row["case_id"],
        created_utc=row["created_utc"],
        report_sha256=row["report_sha256"],
        examiner=row["created_by"] or "",
        pdf_path=pdf_path,
        certificate_path=certificate_path,
        manifest_path=row["manifest_path"],
    )


def list_reports(data_dir: str, case_id: str) -> list[ReportRecord]:
    guarded = appdb.case_db(data_dir, case_id)
    rows = guarded.conn.execute(
        "SELECT * FROM reports WHERE case_id = ? ORDER BY created_utc", (case_id,)
    ).fetchall()
    return [_row_to_report(r) for r in rows]


def get_report(data_dir: str, report_id: str) -> ReportRecord | None:
    for cid in real_store.iter_case_ids(data_dir):
        guarded = appdb.case_db(data_dir, cid)
        row = guarded.conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is not None:
            return _row_to_report(row)
    return None


def get_report_manifest(data_dir: str, report_id: str) -> dict[str, Any] | None:
    report = get_report(data_dir, report_id)
    if report is None or not report.manifest_path:
        return None
    manifest_path = Path(report.manifest_path)
    envelope_path = manifest_path.with_name("envelope.json")
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_bytes())
    envelope = json.loads(envelope_path.read_text("utf-8")) if envelope_path.exists() else {}
    return {**manifest, **envelope}
