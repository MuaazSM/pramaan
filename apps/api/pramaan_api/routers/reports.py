"""Reports and the BSA Section 63 certificate (docs/02-BACKEND.md §4, §9)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Response

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import report_store as real_report_store
from pramaan_api.real import store as real_store
from pramaan_api.schemas import ReportCreate, ReportRecord
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["reports"])

_PLACEHOLDER_PDF = b"%PDF-1.4\n% Pramaan fixture placeholder PDF\n%%EOF\n"


@router.post("/cases/{cid}/reports", response_model=ReportRecord, status_code=201)
def create_report(
    cid: str,
    body: ReportCreate,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> ReportRecord:
    del body  # include_thumbnails: real mode always includes a best-effort set (see report_store)
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.create_report(cid, user.username)
    return real_report_store.create_report(settings, user, cid)


@router.get("/cases/{cid}/reports", response_model=list[ReportRecord])
def list_reports(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[ReportRecord]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_reports(cid)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    return real_report_store.list_reports(settings.data_dir, cid)


def _get_report_or_404(rid: str, settings: Settings) -> ReportRecord:
    report = (
        store.get_report(rid)
        if settings.stub_mode
        else real_report_store.get_report(settings.data_dir, rid)
    )
    if report is None:
        raise not_found("report", rid)
    return report


@router.get("/reports/{rid}/pdf")
def report_pdf(
    rid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> Response:
    report = _get_report_or_404(rid, settings)
    if settings.stub_mode:
        return Response(content=_PLACEHOLDER_PDF, media_type="application/pdf")
    content = Path(report.pdf_path).read_bytes()
    return Response(content=content, media_type="application/pdf")


@router.get("/reports/{rid}/certificate.pdf")
def report_certificate(
    rid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> Response:
    report = _get_report_or_404(rid, settings)
    if settings.stub_mode:
        return Response(content=_PLACEHOLDER_PDF, media_type="application/pdf")
    content = Path(report.certificate_path).read_bytes()
    return Response(content=content, media_type="application/pdf")


@router.get("/reports/{rid}/manifest")
def report_manifest(
    rid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> dict[str, object]:
    report = _get_report_or_404(rid, settings)
    if settings.stub_mode:
        return {
            "report_id": report.id,
            "case_id": report.case_id,
            "report_sha256": report.report_sha256,
            "examiner": report.examiner,
            "created_utc": report.created_utc,
            "limitations": [
                "Synthetic corpus: this demo case is fabricated fixture data, not a real "
                "vendor disk.",
            ],
        }
    manifest = real_report_store.get_report_manifest(settings.data_dir, rid)
    if manifest is None:
        raise not_found("report", rid)
    return manifest
