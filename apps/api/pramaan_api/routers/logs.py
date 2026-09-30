"""Device logs (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import LogEvent

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.real import store as real_store
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["logs"])


@router.get("/cases/{cid}/log-events", response_model=list[LogEvent])
def list_log_events(
    cid: str,
    kind: str | None = None,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[LogEvent]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_log_events(cid, kind=kind)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    # Empty until task C3 lands pramaan_logs.parse_logs — the `logs` stage
    # (apps/worker/pramaan_worker/stages.py) skips gracefully until then,
    # so this table is simply empty rather than special-cased here.
    return real_pipeline.list_log_events(settings.data_dir, cid, kind=kind)
