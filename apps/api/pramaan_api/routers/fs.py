"""Evidence file picker (docs/02-BACKEND.md §4): ``GET /fs/browse?path=``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.fixtures import store
from pramaan_api.schemas import FsEntry
from pramaan_api.security import User

router = APIRouter(tags=["fs"])


@router.get("/fs/browse", response_model=list[FsEntry])
def browse(path: str = "/evidence", user: User = Depends(get_current_user)) -> list[FsEntry]:
    return store.fs_browse(path)
