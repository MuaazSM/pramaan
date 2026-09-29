"""Device logs (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import LogEvent

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.security import User

router = APIRouter(tags=["logs"])


@router.get("/cases/{cid}/log-events", response_model=list[LogEvent])
def list_log_events(
    cid: str, kind: str | None = None, user: User = Depends(get_current_user)
) -> list[LogEvent]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_log_events(cid, kind=kind)
