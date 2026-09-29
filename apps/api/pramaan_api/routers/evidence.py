"""Evidence intake and integrity (docs/02-BACKEND.md §4-5).

Registration, ``/verify`` and ``/scan`` are real in ``STUB_MODE=0`` (task
B1): evidence is hashed through ``pramaan_core`` only, a
``ClockObservation`` is derived from the SWGDE intake, and every mutation
is audited. Fingerprinting and inferred-layout confirmation stay on the
fixture store in every mode — those are C2/B2's real implementations, not
this task's.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import EvidenceImage, InferredLayout, VendorMatch

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import bad_request, not_found
from pramaan_api.fixtures import store
from pramaan_api.real import store as real_store
from pramaan_api.schemas import EvidenceRegister, Job, ScanRequest
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["evidence"])

_SCAN_STAGES = [
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
]


@router.post("/cases/{cid}/evidence", response_model=EvidenceImage, status_code=201)
def register_evidence(
    cid: str,
    body: EvidenceRegister,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> EvidenceImage:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        if not store.is_within_evidence_root(body.path):
            details = {"evidence_roots": ["/evidence"]}
            raise bad_request(f"Path '{body.path}' is outside EVIDENCE_ROOTS.", details)
        return store.register_evidence(cid, body.path, body.label, body.intake)

    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    if not real_store.is_within_evidence_roots(settings.evidence_roots, body.path):
        details = {"evidence_roots": list(settings.evidence_roots)}
        raise bad_request(f"Path '{body.path}' is outside EVIDENCE_ROOTS.", details)
    return real_store.register_evidence(
        settings.data_dir, user, cid, path=body.path, label=body.label, intake=body.intake
    )


@router.get("/cases/{cid}/evidence", response_model=list[EvidenceImage])
def list_evidence(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[EvidenceImage]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_evidence(cid)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    return real_store.list_evidence(settings.data_dir, cid)


@router.get("/evidence/{eid}", response_model=EvidenceImage)
def get_evidence(
    eid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> EvidenceImage:
    image = (
        store.get_evidence(eid)
        if settings.stub_mode
        else real_store.get_evidence(settings.data_dir, eid)
    )
    if image is None:
        raise not_found("evidence", eid)
    return image


@router.post("/evidence/{eid}/verify", response_model=Job, status_code=202)
def verify_evidence(
    eid: str,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> Job:
    if settings.stub_mode:
        image = store.get_evidence(eid)
        if image is None:
            raise not_found("evidence", eid)
        case_id = store.DATA.case.id
        return store.create_job(case_id, eid, "verify", ["hash_verify"])

    found = real_store.get_evidence_with_case(settings.data_dir, eid)
    if found is None:
        raise not_found("evidence", eid)
    case_id, image = found
    return real_store.run_evidence_job(
        settings.data_dir,
        settings.job_backend,
        settings.redis_url,
        user,
        case_id,
        eid,
        image,
        "verify",
        ["hash_verify"],
    )


@router.post("/evidence/{eid}/scan", response_model=Job, status_code=202)
def scan_evidence(
    eid: str,
    body: ScanRequest,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> Job:
    stages = body.stages or _SCAN_STAGES
    if settings.stub_mode:
        image = store.get_evidence(eid)
        if image is None:
            raise not_found("evidence", eid)
        case_id = store.DATA.case.id
        return store.create_job(case_id, eid, "scan", stages)

    found = real_store.get_evidence_with_case(settings.data_dir, eid)
    if found is None:
        raise not_found("evidence", eid)
    case_id, image = found
    return real_store.run_evidence_job(
        settings.data_dir,
        settings.job_backend,
        settings.redis_url,
        user,
        case_id,
        eid,
        image,
        "scan",
        stages,
    )


@router.get("/evidence/{eid}/fingerprint", response_model=list[VendorMatch])
def fingerprint(eid: str, user: User = Depends(get_current_user)) -> list[VendorMatch]:
    # Owned by C2 (fingerprinter) — fixture-backed in every mode until then.
    if store.get_evidence(eid) is None:
        raise not_found("evidence", eid)
    return store.get_vendor_matches(eid)


@router.get("/evidence/{eid}/inferred-layout", response_model=InferredLayout)
def get_inferred_layout(eid: str, user: User = Depends(get_current_user)) -> InferredLayout:
    # Owned by B2/recovery — fixture-backed in every mode until then.
    if store.get_evidence(eid) is None:
        raise not_found("evidence", eid)
    layout = store.get_inferred_layout_for_evidence(eid)
    if layout is None:
        raise not_found("inferred_layout", eid)
    return layout


@router.post("/inferred-layouts/{lid}/confirm", response_model=InferredLayout)
def confirm_inferred_layout(
    lid: str, user: User = Depends(require_examiner_or_admin)
) -> InferredLayout:
    layout = store.confirm_inferred_layout(lid, user.username)
    if layout is None:
        raise not_found("inferred_layout", lid)
    return layout
