"""Deletion findings (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import DeletionFinding

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.real import store as real_store
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["deletions"])


@router.get("/cases/{cid}/deletions", response_model=list[DeletionFinding])
def list_deletions(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[DeletionFinding]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_deletions(cid)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    # Empty until task C3 lands pramaan_recovery.deletion — the
    # `deletion_verdict` stage skips gracefully until then.
    return real_pipeline.list_deletions(settings.data_dir, cid)
