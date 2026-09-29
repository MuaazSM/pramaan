"""Evidence file picker (docs/02-BACKEND.md §4): ``GET /fs/browse?path=``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.fixtures import store
from pramaan_api.real import store as real_store
from pramaan_api.schemas import FsEntry
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["fs"])


@router.get("/fs/browse", response_model=list[FsEntry])
def browse(
    path: str = "/evidence",
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[FsEntry]:
    if settings.stub_mode:
        return store.fs_browse(path)
    return real_store.fs_browse(settings.evidence_roots, path)
