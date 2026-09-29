"""Clip streaming with HTTP Range support (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from pramaan_api.deps import get_current_user
from pramaan_api.errors import bad_request, not_found
from pramaan_api.fixtures import store
from pramaan_api.security import User

router = APIRouter(tags=["clips"])


@router.get("/clips/{clip_id}/stream")
def stream_clip(clip_id: str, request: Request, user: User = Depends(get_current_user)) -> Response:
    clip = store.get_clip(clip_id)
    if clip is None:
        raise not_found("clip", clip_id)
    data = store.clip_bytes(clip)
    total = len(data)
    range_header = request.headers.get("range")
    if range_header is None:
        return Response(
            content=data,
            media_type="video/mp4",
            headers={"Accept-Ranges": "bytes", "Content-Length": str(total)},
        )
    start, end = _parse_range(range_header, total)
    chunk = data[start : end + 1]
    return Response(
        content=chunk,
        status_code=206,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(len(chunk)),
        },
    )


def _parse_range(range_header: str, total: int) -> tuple[int, int]:
    if not range_header.startswith("bytes="):
        raise bad_request(f"Unsupported Range header '{range_header}'.")
    spec = range_header.removeprefix("bytes=")
    start_s, _, end_s = spec.partition("-")
    try:
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else total - 1
    except ValueError as exc:
        raise bad_request(f"Malformed Range header '{range_header}'.") from exc
    end = min(end, total - 1)
    if start < 0 or start > end:
        raise bad_request(f"Unsatisfiable Range header '{range_header}'.")
    return start, end
