"""Reports and the BSA Section 63 certificate (docs/02-BACKEND.md §4, §9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from pramaan_api.deps import get_current_user, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import ReportCreate, ReportRecord
from pramaan_api.security import User

router = APIRouter(tags=["reports"])


@router.post("/cases/{cid}/reports", response_model=ReportRecord, status_code=201)
def create_report(
    cid: str, body: ReportCreate, user: User = Depends(require_examiner_or_admin)
) -> ReportRecord:
    del body
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.create_report(cid, user.username)


@router.get("/cases/{cid}/reports", response_model=list[ReportRecord])
def list_reports(cid: str, user: User = Depends(get_current_user)) -> list[ReportRecord]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_reports(cid)


def _get_report_or_404(rid: str) -> ReportRecord:
    report = store.get_report(rid)
    if report is None:
        raise not_found("report", rid)
    return report


@router.get("/reports/{rid}/pdf")
def report_pdf(rid: str, user: User = Depends(get_current_user)) -> Response:
    _get_report_or_404(rid)
    placeholder = b"%PDF-1.4\n% Pramaan fixture placeholder report PDF\n%%EOF\n"
    return Response(content=placeholder, media_type="application/pdf")


@router.get("/reports/{rid}/certificate.pdf")
def report_certificate(rid: str, user: User = Depends(get_current_user)) -> Response:
    _get_report_or_404(rid)
    placeholder = b"%PDF-1.4\n% Pramaan fixture placeholder BSA Section 63 certificate\n%%EOF\n"
    return Response(content=placeholder, media_type="application/pdf")


@router.get("/reports/{rid}/manifest")
def report_manifest(rid: str, user: User = Depends(get_current_user)) -> dict[str, object]:
    report = _get_report_or_404(rid)
    return {
        "report_id": report.id,
        "case_id": report.case_id,
        "report_sha256": report.report_sha256,
        "examiner": report.examiner,
        "created_utc": report.created_utc,
        "limitations": [
            "Synthetic corpus: this demo case is fabricated fixture data, not a real vendor disk.",
        ],
    }
