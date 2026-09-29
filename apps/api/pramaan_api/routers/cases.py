"""Cases (docs/02-BACKEND.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import Case, CaseCreate, CasePatch
from pramaan_api.security import User

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=list[Case])
def list_cases(user: User = Depends(get_current_user)) -> list[Case]:
    return store.list_cases()


@router.post("/cases", response_model=Case, status_code=201)
def create_case(body: CaseCreate, user: User = Depends(get_current_user)) -> Case:
    # Wave 0 stub: the fixture dataset ships exactly one case (CR-2026-0412).
    # A real implementation persists a new row; this echoes the seed case so
    # the response shape is exercisable by WEB tonight.
    del body
    return store.DATA.case


@router.get("/cases/{cid}", response_model=Case)
def get_case(cid: str, user: User = Depends(get_current_user)) -> Case:
    case = store.get_case(cid)
    if case is None:
        raise not_found("case", cid)
    return case


@router.patch("/cases/{cid}", response_model=Case)
def patch_case(cid: str, body: CasePatch, user: User = Depends(get_current_user)) -> Case:
    updated = store.patch_case(
        cid, title=body.title, fir_reference=body.fir_reference, lab=body.lab, status=body.status
    )
    if updated is None:
        raise not_found("case", cid)
    return updated
