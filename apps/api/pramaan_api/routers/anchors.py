"""Merkle anchoring (docs/02-BACKEND.md §4, §8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import Anchor, AnchorCreate
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["anchors"])


@router.post("/cases/{cid}/anchors", response_model=Anchor, status_code=201)
def create_anchor(
    cid: str,
    body: AnchorCreate,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
) -> Anchor:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    backend = body.backend or settings.anchor_backend
    return store.create_anchor(cid, backend)


@router.get("/cases/{cid}/anchors", response_model=list[Anchor])
def list_anchors(cid: str, user: User = Depends(get_current_user)) -> list[Anchor]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_anchors(cid)
