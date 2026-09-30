"""Recordings table (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pramaan_core.models import Recording

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.real import store as real_store
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["recordings"])


@router.get("/cases/{cid}/recordings", response_model=list[Recording])
def list_recordings(
    cid: str,
    channel: int | None = None,
    source: Literal["index", "carved", "inferred"] | None = None,
    deleted: bool | None = None,
    from_: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[Recording]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_recordings(
            cid, channel=channel, source=source, deleted=deleted, frm=from_, to=to
        )
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    return real_pipeline.list_recordings(
        settings.data_dir, cid, channel=channel, source=source, deleted=deleted, frm=from_, to=to
    )


@router.get("/recordings/{rid}", response_model=Recording)
def get_recording(
    rid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> Recording:
    rec = (
        store.get_recording(rid)
        if settings.stub_mode
        else real_pipeline.get_recording(settings.data_dir, rid)
    )
    if rec is None:
        raise not_found("recording", rid)
    return rec
