"""Command palette search (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.fixtures import store
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.schemas import SearchResult
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchResult])
def search(
    q: str = "", user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[SearchResult]:
    if settings.stub_mode:
        return store.search(q)
    return real_pipeline.search(settings.data_dir, q)
