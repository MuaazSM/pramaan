"""Motion triage and detection (docs/02-BACKEND.md §2, §4;
docs/03-AI-TIMELINE.md §6-7).

See the module docstring in ``routers/timeline.py`` for the stub-vs-real
pattern every AI-owned router follows, and for why importing this module
also registers the real ``motion`` pipeline stage
(``pramaan_analytics.motion.motion_stage``) through B2's
``pramaan_worker.stages.register_stage`` hook.

Detection (docs §7, P2) stays fixture-only / empty in real mode — explicitly
out of scope for this task (no detector model is bundled).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pramaan_analytics.motion import motion_stage
from pramaan_core.models import Detection, MotionSegment
from pramaan_worker.runner import STAGE_NAMES
from pramaan_worker.stages import register_stage
from pydantic import BaseModel, ConfigDict

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import bad_request, not_found
from pramaan_api.fixtures import store
from pramaan_api.real import appdb
from pramaan_api.real import store as real_store
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

register_stage("motion", motion_stage)

router = APIRouter(tags=["analytics"])

#: The AI-owned subset of the pipeline this router's ``/analytics/run`` can
#: (re-)drive on demand, per docs/03-AI-TIMELINE.md §5/§6.
_AI_STAGE_NAMES = ("timeline", "motion")


class AnalyticsRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[str] | None = None
    #: Real mode only: which evidence image to run on. Optional when the
    #: case has exactly one image (the common case in this demo/corpus
    #: scale); required (400 otherwise) when it has more than one.
    evidence_id: str | None = None


class AnalyticsRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str


# --- real-mode data access (motion_segments; B2's pipeline_store has no
# helper for this table — see routers/timeline.py's matching note) ----------


def _row_to_motion_segment(row: Any) -> MotionSegment:
    return MotionSegment(
        id=row["id"],
        image_id=row["image_id"],
        channel=row["channel"],
        start_norm_us=row["start_norm_us"],
        end_norm_us=row["end_norm_us"],
        peak_score=row["peak_score"],
        frames=row["frames"],
    )


def real_list_motion_segments(
    data_dir: str, case_id: str, *, channel: int | None = None
) -> list[MotionSegment]:
    images = real_store.list_evidence(data_dir, case_id)
    if not images:
        return []
    conn = appdb.case_db(data_dir, case_id).conn
    placeholders = ",".join("?" for _ in images)
    sql = f"SELECT * FROM motion_segments WHERE image_id IN ({placeholders})"
    params: list[Any] = [img.id for img in images]
    if channel is not None:
        sql += " AND channel = ?"
        params.append(channel)
    sql += " ORDER BY channel, start_norm_us"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_motion_segment(r) for r in rows]


@router.get("/cases/{cid}/motion", response_model=list[MotionSegment])
def list_motion(
    cid: str,
    channel: int | None = None,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[MotionSegment]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_motion_segments(cid, channel=channel)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    return real_list_motion_segments(settings.data_dir, cid, channel=channel)


@router.get("/cases/{cid}/detections", response_model=list[Detection])
def list_detections(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[Detection]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_detections(cid)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    # Detection (docs/03-AI-TIMELINE.md §7, P2) is out of scope for this
    # task — no detector model is bundled, so real mode always returns [].
    return []


@router.post("/cases/{cid}/analytics/run", response_model=AnalyticsRunResult, status_code=202)
def run_analytics(
    cid: str,
    body: AnalyticsRunRequest,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> AnalyticsRunResult:
    requested = body.stages or ["motion"]
    stages = [s for s in requested if s in STAGE_NAMES] or list(_AI_STAGE_NAMES)

    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        job = store.create_job(cid, None, "scan", stages)
        return AnalyticsRunResult(job_id=job.id, status=job.status)

    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    images = real_store.list_evidence(settings.data_dir, cid)
    if body.evidence_id is not None:
        image = next((i for i in images if i.id == body.evidence_id), None)
        if image is None:
            raise not_found("evidence", body.evidence_id)
    elif len(images) == 1:
        image = images[0]
    else:
        raise bad_request(
            "This case has more than one evidence image; pass 'evidence_id' to choose one."
            if images
            else "This case has no evidence images to run analytics on."
        )

    job = real_store.run_evidence_job(
        settings.data_dir,
        settings.job_backend,
        settings.redis_url,
        user,
        cid,
        image.id,
        image,
        "scan",
        stages,
    )
    return AnalyticsRunResult(job_id=job.id, status=job.status)
