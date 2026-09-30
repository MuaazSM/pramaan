"""Evidence intake and integrity (docs/02-BACKEND.md §4-5).

Registration, ``/verify`` and ``/scan`` are real in ``STUB_MODE=0`` (task
B1). Fingerprint/inferred-layout GETs are real too (task B2, backed by the
``fingerprint``/``infer_layout`` pipeline stages in
``apps/worker/pramaan_worker/stages.py``) — inferred-layout stays empty
until task C3 lands ``pramaan_recovery.infer``. Inferred-layout
*confirmation* stays fixture-only in every mode for now (nothing to
confirm in real mode yet).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import EvidenceImage, InferredLayout, VendorMatch
from pramaan_worker.runner import STAGE_NAMES

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import bad_request, not_found
from pramaan_api.fixtures import store
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.real import store as real_store
from pramaan_api.schemas import EvidenceRegister, Job, ScanRequest
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["evidence"])


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
    stages = body.stages or list(STAGE_NAMES)
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
def fingerprint(
    eid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[VendorMatch]:
    if settings.stub_mode:
        if store.get_evidence(eid) is None:
            raise not_found("evidence", eid)
        return store.get_vendor_matches(eid)
    if real_store.get_evidence(settings.data_dir, eid) is None:
        raise not_found("evidence", eid)
    return real_pipeline.list_vendor_matches(settings.data_dir, eid)


@router.get("/evidence/{eid}/inferred-layout", response_model=InferredLayout)
def get_inferred_layout(
    eid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> InferredLayout:
    if settings.stub_mode:
        if store.get_evidence(eid) is None:
            raise not_found("evidence", eid)
        layout = store.get_inferred_layout_for_evidence(eid)
    else:
        if real_store.get_evidence(settings.data_dir, eid) is None:
            raise not_found("evidence", eid)
        layout = real_pipeline.get_inferred_layout(settings.data_dir, eid)
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
