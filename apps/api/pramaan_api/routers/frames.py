"""Frame search, prove-it hex view, thumbnails (docs/02-BACKEND.md §4)."""

from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pramaan_core.models import FrameRef

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import HexView
from pramaan_api.security import User

router = APIRouter(tags=["frames"])


@router.get("/cases/{cid}/frames", response_model=list[FrameRef])
def list_frames(
    cid: str,
    channel: int | None = None,
    source: Literal["index", "carved", "inferred"] | None = None,
    deleted: bool | None = None,
    frame_type: str | None = None,
    from_: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    limit: int = Query(default=500, le=500, gt=0),
    user: User = Depends(get_current_user),
) -> list[FrameRef]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    frames = store.list_frames(
        cid,
        channel=channel,
        source=source,
        deleted=deleted,
        frame_type=frame_type,
        frm=from_,
        to=to,
    )
    return frames[:limit]


@router.get("/frames/{fid}", response_model=FrameRef)
def get_frame(fid: str, user: User = Depends(get_current_user)) -> FrameRef:
    frame = store.get_frame(fid)
    if frame is None:
        raise not_found("frame", fid)
    return frame


@router.get("/frames/{fid}/hex", response_model=HexView)
def frame_hex(
    fid: str,
    before: int = Query(default=256, ge=0, le=8192),
    after: int = Query(default=512, ge=0, le=8192),
    user: User = Depends(get_current_user),
) -> HexView:
    frame = store.get_frame(fid)
    if frame is None:
        raise not_found("frame", fid)
    view = store.frame_hex_view(frame, before, after)
    payload_bytes = view["bytes"]
    assert isinstance(payload_bytes, bytes)
    recomputed = view["payload_sha256_recomputed"]
    stored = view["payload_sha256_stored"]
    assert isinstance(recomputed, str)
    assert isinstance(stored, str)
    annotations = view["annotations"]
    assert isinstance(annotations, list)
    offset = view["offset"]
    assert isinstance(offset, int)
    return HexView(
        frame_id=fid,
        offset=offset,
        before=before,
        after=after,
        bytes_b64=base64.b64encode(payload_bytes).decode("ascii"),
        annotations=annotations,
        payload_sha256_recomputed=recomputed,
        payload_sha256_stored=stored,
        matches=recomputed == stored,
    )


@router.get("/frames/{fid}/thumb")
def frame_thumb(fid: str, user: User = Depends(get_current_user)) -> Response:
    frame = store.get_frame(fid)
    if frame is None:
        raise not_found("frame", fid)
    return Response(content=store.frame_thumb_bytes(frame), media_type="image/jpeg")
