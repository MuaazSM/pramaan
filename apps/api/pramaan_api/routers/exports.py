"""Signed MP4 export (docs/02-BACKEND.md §4, §10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, UploadFile

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import export_store as real_export_store
from pramaan_api.schemas import ExportCreate, ExportRecord, ExportVerifyResult
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["exports"])


@router.post("/cases/{cid}/exports", response_model=ExportRecord, status_code=201)
def create_export(
    cid: str,
    body: ExportCreate,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> ExportRecord:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.create_export(
            cid, user.username, body.recording_id, body.channel, body.from_norm_us, body.to_norm_us
        )
    return real_export_store.create_export(
        settings,
        user,
        cid,
        recording_id=body.recording_id,
        channel=body.channel,
        from_norm_us=body.from_norm_us,
        to_norm_us=body.to_norm_us,
    )


@router.get("/exports/{xid}/file")
def export_file(
    xid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> Response:
    if settings.stub_mode:
        export = store.get_export(xid)
        if export is None:
            raise not_found("export", xid)
        placeholder = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 512
        return Response(content=placeholder, media_type="video/mp4")
    path = real_export_store.get_export_file_path(settings.data_dir, xid)
    if path is None or not path.exists():
        raise not_found("export", xid)
    return Response(content=path.read_bytes(), media_type="video/mp4")


@router.post("/exports/verify", response_model=ExportVerifyResult)
async def verify_export(
    file: UploadFile,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ExportVerifyResult:
    content = await file.read()
    if settings.stub_mode:
        # Wave 0 stub: a real implementation parses the embedded manifest box
        # and checks the Ed25519 signature (packages/export). Here we just
        # report whether the fixture prefix looks intact, which is enough
        # for WEB to build the verify screen against a realistic shape.
        looks_intact = content.startswith(b"\x00\x00\x00\x18ftyp")
        return ExportVerifyResult(
            signature_valid=looks_intact,
            manifest={"note": "fixture stub — real manifest parsing is packages/export's job"},
            source_matches_registered_evidence=looks_intact,
        )
    outcome, source_matches = real_export_store.verify_export(settings.data_dir, content)
    manifest: dict[str, object] = dict(outcome.manifest)
    if outcome.reasons:
        manifest["_verification_notes"] = list(outcome.reasons)
    return ExportVerifyResult(
        signature_valid=outcome.signature_valid,
        manifest=manifest,
        source_matches_registered_evidence=source_matches,
    )
