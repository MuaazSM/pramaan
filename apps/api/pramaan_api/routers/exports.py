"""Signed MP4 export (docs/02-BACKEND.md §4, §10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, UploadFile

from pramaan_api.deps import get_current_user, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import ExportCreate, ExportRecord, ExportVerifyResult
from pramaan_api.security import User

router = APIRouter(tags=["exports"])


@router.post("/cases/{cid}/exports", response_model=ExportRecord, status_code=201)
def create_export(
    cid: str, body: ExportCreate, user: User = Depends(require_examiner_or_admin)
) -> ExportRecord:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.create_export(
        cid, user.username, body.recording_id, body.channel, body.from_norm_us, body.to_norm_us
    )


@router.get("/exports/{xid}/file")
def export_file(xid: str, user: User = Depends(get_current_user)) -> Response:
    export = store.get_export(xid)
    if export is None:
        raise not_found("export", xid)
    placeholder = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 512
    return Response(content=placeholder, media_type="video/mp4")


@router.post("/exports/verify", response_model=ExportVerifyResult)
async def verify_export(
    file: UploadFile, user: User = Depends(get_current_user)
) -> ExportVerifyResult:
    content = await file.read()
    # Wave 0 stub: a real implementation parses the embedded manifest box and
    # checks the Ed25519 signature (packages/export). Here we just report
    # whether the fixture prefix looks intact, which is enough for WEB to
    # build the verify screen against a realistic shape tonight.
    looks_intact = content.startswith(b"\x00\x00\x00\x18ftyp")
    return ExportVerifyResult(
        signature_valid=looks_intact,
        manifest={"note": "fixture stub — real manifest parsing is packages/export's job"},
        source_matches_registered_evidence=looks_intact,
    )
