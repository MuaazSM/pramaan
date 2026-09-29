"""Command palette search (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.fixtures import store
from pramaan_api.schemas import SearchResult
from pramaan_api.security import User

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchResult])
def search(q: str = "", user: User = Depends(get_current_user)) -> list[SearchResult]:
    return store.search(q)
