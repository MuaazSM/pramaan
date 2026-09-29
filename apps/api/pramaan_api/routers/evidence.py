"""Evidence intake and integrity (docs/02-BACKEND.md §4–5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import EvidenceImage, InferredLayout, VendorMatch

from pramaan_api.deps import get_current_user, require_examiner_or_admin
from pramaan_api.errors import bad_request, not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import EvidenceRegister, Job, ScanRequest
from pramaan_api.security import User

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
    cid: str, body: EvidenceRegister, user: User = Depends(require_examiner_or_admin)
) -> EvidenceImage:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    if not store.is_within_evidence_root(body.path):
        details = {"evidence_roots": ["/evidence"]}
        raise bad_request(f"Path '{body.path}' is outside EVIDENCE_ROOTS.", details)
    return store.register_evidence(cid, body.path, body.label, body.intake)


@router.get("/cases/{cid}/evidence", response_model=list[EvidenceImage])
def list_evidence(cid: str, user: User = Depends(get_current_user)) -> list[EvidenceImage]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_evidence(cid)


@router.get("/evidence/{eid}", response_model=EvidenceImage)
def get_evidence(eid: str, user: User = Depends(get_current_user)) -> EvidenceImage:
    image = store.get_evidence(eid)
    if image is None:
        raise not_found("evidence", eid)
    return image


@router.post("/evidence/{eid}/verify", response_model=Job, status_code=202)
def verify_evidence(eid: str, user: User = Depends(get_current_user)) -> Job:
    image = store.get_evidence(eid)
    if image is None:
        raise not_found("evidence", eid)
    case_id = store.DATA.case.id
    return store.create_job(case_id, eid, "verify", ["hash_verify"])


@router.post("/evidence/{eid}/scan", response_model=Job, status_code=202)
def scan_evidence(
    eid: str, body: ScanRequest, user: User = Depends(require_examiner_or_admin)
) -> Job:
    image = store.get_evidence(eid)
    if image is None:
        raise not_found("evidence", eid)
    stages = body.stages or _SCAN_STAGES
    case_id = store.DATA.case.id
    return store.create_job(case_id, eid, "scan", stages)


@router.get("/evidence/{eid}/fingerprint", response_model=list[VendorMatch])
def fingerprint(eid: str, user: User = Depends(get_current_user)) -> list[VendorMatch]:
    if store.get_evidence(eid) is None:
        raise not_found("evidence", eid)
    return store.get_vendor_matches(eid)


@router.get("/evidence/{eid}/inferred-layout", response_model=InferredLayout)
def get_inferred_layout(eid: str, user: User = Depends(get_current_user)) -> InferredLayout:
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
