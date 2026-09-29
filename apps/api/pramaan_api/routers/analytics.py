"""Motion triage and detection (AI-owned from Wave 2 — docs/02-BACKEND.md §2,
§4; docs/03-AI-TIMELINE.md §6–7).

Thin, self-contained typed stub (see the module docstring in
``routers/timeline.py`` for the pattern every AI-owned router file follows).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pramaan_core.models import Detection, MotionSegment
from pydantic import BaseModel, ConfigDict

from pramaan_api.deps import get_current_user, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.security import User

router = APIRouter(tags=["analytics"])


class AnalyticsRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[str] | None = None


class AnalyticsRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str


@router.get("/cases/{cid}/motion", response_model=list[MotionSegment])
def list_motion(
    cid: str, channel: int | None = None, user: User = Depends(get_current_user)
) -> list[MotionSegment]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_motion_segments(cid, channel=channel)


@router.get("/cases/{cid}/detections", response_model=list[Detection])
def list_detections(cid: str, user: User = Depends(get_current_user)) -> list[Detection]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_detections(cid)


@router.post("/cases/{cid}/analytics/run", response_model=AnalyticsRunResult, status_code=202)
def run_analytics(
    cid: str, body: AnalyticsRunRequest, user: User = Depends(require_examiner_or_admin)
) -> AnalyticsRunResult:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    stages = body.stages or ["motion"]
    job = store.create_job(cid, None, "scan", stages)
    return AnalyticsRunResult(job_id=job.id, status=job.status)
