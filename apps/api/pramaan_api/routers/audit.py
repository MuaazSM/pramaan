"""Chain of custody (docs/02-BACKEND.md §4, §8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import store as real_store
from pramaan_api.schemas import AuditEntry, AuditVerifyResult, Page
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["audit"])


@router.get("/cases/{cid}/audit", response_model=Page[AuditEntry])
def list_audit(
    cid: str,
    cursor: str | None = None,
    limit: int | None = None,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Page[AuditEntry]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        items, next_cursor = store.list_audit(cid, cursor=cursor, limit=limit)
    else:
        if real_store.get_case(settings.data_dir, cid) is None:
            raise not_found("case", cid)
        items, next_cursor = real_store.list_audit(
            settings.data_dir, cid, cursor=cursor, limit=limit
        )
    return Page[AuditEntry](items=items, next_cursor=next_cursor)


@router.get("/cases/{cid}/audit/verify", response_model=AuditVerifyResult)
def verify_audit(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> AuditVerifyResult:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.verify_audit(cid)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    return real_store.verify_audit(settings.data_dir, cid)
