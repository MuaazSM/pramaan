"""Deletion findings (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import DeletionFinding

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.security import User

router = APIRouter(tags=["deletions"])


@router.get("/cases/{cid}/deletions", response_model=list[DeletionFinding])
def list_deletions(cid: str, user: User = Depends(get_current_user)) -> list[DeletionFinding]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_deletions(cid)
