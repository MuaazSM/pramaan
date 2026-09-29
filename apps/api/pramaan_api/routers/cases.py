"""Cases (docs/02-BACKEND.md §4).

In ``STUB_MODE=1`` (default) this still serves the fixture dataset's single
demo case unchanged, per docs/PROMPTBOOK.md B1's "keep the demo fixtures
working" instruction. In real mode (``STUB_MODE=0``) cases are persisted
(``pramaan_api.real.store``, ``<data_dir>/app.db``'s ``cases`` table) and
every mutation is audited.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import store as real_store
from pramaan_api.schemas import Case, CaseCreate, CasePatch
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=list[Case])
def list_cases(
    user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[Case]:
    if settings.stub_mode:
        return store.list_cases()
    return real_store.list_cases(settings.data_dir)


@router.post("/cases", response_model=Case, status_code=201)
def create_case(
    body: CaseCreate,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> Case:
    if settings.stub_mode:
        # Wave 0 stub: the fixture dataset ships exactly one case
        # (CR-2026-0412); echo it so the response shape is exercisable.
        del body
        return store.DATA.case
    return real_store.create_case(
        settings.data_dir,
        user,
        case_number=body.case_number,
        title=body.title,
        fir_reference=body.fir_reference,
        lab=body.lab,
    )


@router.get("/cases/{cid}", response_model=Case)
def get_case(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> Case:
    case = (
        store.get_case(cid) if settings.stub_mode else real_store.get_case(settings.data_dir, cid)
    )
    if case is None:
        raise not_found("case", cid)
    return case


@router.patch("/cases/{cid}", response_model=Case)
def patch_case(
    cid: str,
    body: CasePatch,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> Case:
    if settings.stub_mode:
        updated = store.patch_case(
            cid,
            title=body.title,
            fir_reference=body.fir_reference,
            lab=body.lab,
            status=body.status,
        )
    else:
        updated = real_store.patch_case(
            settings.data_dir,
            user,
            cid,
            title=body.title,
            fir_reference=body.fir_reference,
            lab=body.lab,
            status=body.status,
        )
    if updated is None:
        raise not_found("case", cid)
    return updated
