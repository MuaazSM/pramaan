"""Frame search, prove-it hex view, thumbnails (docs/02-BACKEND.md §4)."""

from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pramaan_core.models import FrameRef

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.real import store as real_store
from pramaan_api.schemas import HexView
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["frames"])

#: Additive response header on ``GET /cases/{cid}/frames`` carrying the
#: *unpaginated* match count (task FIX-1) — the 500-row page cap on the
#: JSON body (docs/02-BACKEND.md §4) is unchanged; this lets a client (e.g.
#: `just demo`) report exact counts instead of treating a full page as a
#: lower bound.
_TOTAL_COUNT_HEADER = "X-Total-Count"


@router.get("/cases/{cid}/frames", response_model=list[FrameRef])
def list_frames(
    cid: str,
    response: Response,
    channel: int | None = None,
    source: Literal["index", "carved", "inferred"] | None = None,
    deleted: bool | None = None,
    frame_type: str | None = None,
    from_: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    limit: int = Query(default=500, le=500, gt=0),
    offset: int = Query(
        default=0,
        ge=0,
        description=(
            "Task FIX-4: a stable, deterministic page offset over the same total order "
            "the response is sorted in (channel, ts_header_us, payload_offset) — additive "
            "alongside, not a replacement for, `from`/`to` (which filter on ts_header_us and "
            "so cannot reach generic-carved frames with no device-clock header, e.g. XSIM's "
            "blind carve pass). Combine with the `X-Total-Count` response header to page "
            "through every frame regardless of whether it has a timestamp."
        ),
    ),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[FrameRef]:
    if settings.stub_mode:
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
        response.headers[_TOTAL_COUNT_HEADER] = str(len(frames))
        return frames[offset : offset + limit]
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    total = real_pipeline.count_frames(
        settings.data_dir,
        cid,
        channel=channel,
        source=source,
        deleted=deleted,
        frame_type=frame_type,
        frm=from_,
        to=to,
    )
    response.headers[_TOTAL_COUNT_HEADER] = str(total)
    return real_pipeline.list_frames(
        settings.data_dir,
        cid,
        channel=channel,
        source=source,
        deleted=deleted,
        frame_type=frame_type,
        frm=from_,
        to=to,
        limit=limit,
        offset=offset,
    )


@router.get("/frames/{fid}", response_model=FrameRef)
def get_frame(
    fid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> FrameRef:
    frame = (
        store.get_frame(fid)
        if settings.stub_mode
        else real_pipeline.get_frame(settings.data_dir, fid)
    )
    if frame is None:
        raise not_found("frame", fid)
    return frame


@router.get("/frames/{fid}/hex", response_model=HexView)
def frame_hex(
    fid: str,
    before: int = Query(default=256, ge=0, le=8192),
    after: int = Query(default=512, ge=0, le=8192),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> HexView:
    if settings.stub_mode:
        frame = store.get_frame(fid)
        if frame is None:
            raise not_found("frame", fid)
        view = store.frame_hex_view(frame, before, after)
    else:
        view_or_none = real_pipeline.frame_hex_view(settings.data_dir, fid, before, after)
        if view_or_none is None:
            raise not_found("frame", fid)
        view = view_or_none

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
    # Stub frames fabricate bytes so recomputed == stored always; real
    # frames' "stored" claim is FrameRef.frame_id = sha256(payload)[:24]
    # (pipeline_store.frame_hex_view already supplies "matches" for that
    # prefix comparison).
    matches = bool(view["matches"]) if "matches" in view else recomputed == stored
    return HexView(
        frame_id=fid,
        offset=offset,
        before=before,
        after=after,
        bytes_b64=base64.b64encode(payload_bytes).decode("ascii"),
        annotations=annotations,
        payload_sha256_recomputed=recomputed,
        payload_sha256_stored=stored,
        matches=matches,
    )


@router.get("/frames/{fid}/thumb")
def frame_thumb(
    fid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> Response:
    if settings.stub_mode:
        frame = store.get_frame(fid)
        if frame is None:
            raise not_found("frame", fid)
        return Response(content=store.frame_thumb_bytes(frame), media_type="image/jpeg")

    thumb_bytes = real_pipeline.frame_thumbnail_bytes(settings.data_dir, fid)
    if thumb_bytes is None:
        raise not_found("frame_thumbnail", fid)
    return Response(
        content=thumb_bytes,
        media_type="image/jpeg",
        headers={"X-Pramaan-Derived": "true"},
    )
