"""Job status (docs/02-BACKEND.md §4, §6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.deps import get_current_user
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.schemas import Job
from pramaan_api.security import User

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{jid}", response_model=Job)
def get_job(jid: str, user: User = Depends(get_current_user)) -> Job:
    job = store.get_job(jid)
    if job is None:
        raise not_found("job", jid)
    return job


@router.get("/cases/{cid}/jobs", response_model=list[Job])
def list_jobs(cid: str, user: User = Depends(get_current_user)) -> list[Job]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_jobs(cid)
