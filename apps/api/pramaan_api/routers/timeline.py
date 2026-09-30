"""Timeline (docs/02-BACKEND.md §2, §4; docs/03-AI-TIMELINE.md §3, §5).

W0.3 shipped this as a thin, self-contained typed stub returning fixture
data. Task A2 fills in the real (``stub_mode=False``) side: real-mode reads
go straight at ``case.db``'s ``clock_models``/``log_events`` tables and the
Parquet frame index (via ``pramaan_api.real.pipeline_store``, B2's real-mode
data layer, and small local queries for the ``clock_models`` table B2 didn't
need); stub mode is untouched, byte-for-byte, so it keeps serving fixtures
regardless of what real mode is doing (per this task's brief: "Stub mode
must keep serving fixtures").

Importing this module registers the real ``timeline`` pipeline stage
(``pramaan_timeline.pipeline.timeline_stage``) through B2's hook
(``pramaan_worker.stages.register_stage`` — docs/progress/B2.md
"Integration contract"); ``main.py`` mounts every router at startup, so this
runs exactly once per process, before any scan job can run.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pramaan_core.models import ClockModel, ClockSegment
from pramaan_timeline.pipeline import timeline_stage
from pramaan_worker.stages import register_stage
from pydantic import BaseModel, ConfigDict

from pramaan_api.deps import get_current_user, require_csrf, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.real import appdb
from pramaan_api.real import pipeline_store as real_pipeline
from pramaan_api.real import store as real_store
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

register_stage("timeline", timeline_stage)

router = APIRouter(tags=["timeline"])


class ChannelClockSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: float
    summary: str


class ChannelTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str
    channel: int
    label: str
    color_token: str
    coverage: list[tuple[int, int, Literal["index", "carved", "inferred"]]]
    deleted: list[tuple[int, int, str]]
    motion: list[tuple[int, float]]
    clock: ChannelClockSummary


class TimelineMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts_norm_us: int
    kind: str
    log_event_id: str
    user: str | None


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int
    end: int
    channels: list[int]
    kind: str


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[ChannelTimeline]
    markers: list[TimelineMarker]
    events: list[TimelineEvent]


class ClockOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset_us: int | None = None
    reason: str


# --- real-mode data access (B2's pipeline_store has no clock_models/motion
# helpers — its own scope was recordings/frames/clips/logs/deletions/search,
# docs/progress/B2.md — so this small, additive read layer lives here) ------


def _row_to_clock_model(row: Any) -> ClockModel:
    return ClockModel(
        id=row["id"],
        image_id=row["image_id"],
        channel=row["channel"],
        segments=[ClockSegment(**s) for s in json.loads(row["segments"])],
        osd_offset_us=row["osd_offset_us"],
        confidence=row["confidence"],
        residual_ms=row["residual_ms"],
        method=row["method"],
        overridden_by=row["overridden_by"],
    )


def real_list_clock_models(data_dir: str, case_id: str) -> list[ClockModel]:
    images = real_store.list_evidence(data_dir, case_id)
    if not images:
        return []
    conn = appdb.case_db(data_dir, case_id).conn
    placeholders = ",".join("?" for _ in images)
    rows = conn.execute(
        f"SELECT * FROM clock_models WHERE image_id IN ({placeholders})"
        " ORDER BY image_id, channel",
        [img.id for img in images],
    ).fetchall()
    return [_row_to_clock_model(r) for r in rows]


def real_find_clock_model(data_dir: str, model_id: str) -> tuple[str, ClockModel] | None:
    for cid in real_store.iter_case_ids(data_dir):
        conn = appdb.case_db(data_dir, cid).conn
        row = conn.execute("SELECT * FROM clock_models WHERE id = ?", (model_id,)).fetchone()
        if row is not None:
            return cid, _row_to_clock_model(row)
    return None


def real_override_clock_model(
    data_dir: str, model_id: str, examiner: str
) -> tuple[str, ClockModel] | None:
    found = real_find_clock_model(data_dir, model_id)
    if found is None:
        return None
    case_id, model = found
    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        guarded.conn.execute(
            "UPDATE clock_models SET overridden_by = ? WHERE id = ?", (examiner, model_id)
        )
        guarded.conn.commit()
    updated = model.model_copy(update={"overridden_by": examiner})
    return case_id, updated


def real_list_channels(data_dir: str, case_id: str) -> list[dict[str, Any]]:
    recs = real_pipeline.list_recordings(data_dir, case_id)
    channels = sorted({r.channel for r in recs})
    return [{"channel": c, "label": f"CH{c}", "color_token": f"--ch-{c}"} for c in channels]


def _real_channel_timeline(data_dir: str, case_id: str, ch_info: dict[str, Any]) -> ChannelTimeline:
    channel = ch_info["channel"]
    recs = real_pipeline.list_recordings(data_dir, case_id, channel=channel)
    coverage = [(r.start_ts_us or 0, r.end_ts_us or 0, r.source) for r in recs if not r.deleted]
    deleted_ranges = [
        (f.start_ts_us, f.end_ts_us, f.id)
        for f in real_pipeline.list_deletions(data_dir, case_id)
        if f.channel is None or f.channel == channel
    ]
    from pramaan_api.routers.analytics import real_list_motion_segments

    chan_motion = real_list_motion_segments(data_dir, case_id, channel=channel)
    motion = [(m.start_norm_us, m.peak_score) for m in chan_motion]
    clock_model = next(
        (m for m in real_list_clock_models(data_dir, case_id) if m.channel == channel), None
    )
    clock = ChannelClockSummary(
        confidence=clock_model.confidence if clock_model else 0.0,
        summary=clock_model.method if clock_model else "no clock model",
    )
    return ChannelTimeline(
        image_id=recs[0].image_id if recs else "",
        channel=channel,
        label=ch_info["label"],
        color_token=ch_info["color_token"],
        coverage=coverage,
        deleted=deleted_ranges,
        motion=motion,
        clock=clock,
    )


def _co_motion_events(segments: list[Any]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for i, seg in enumerate(segments):
        for other in segments[i + 1 :]:
            if seg.channel == other.channel:
                continue
            overlaps = (
                seg.start_norm_us <= other.end_norm_us + 2_000_000
                and other.start_norm_us <= seg.end_norm_us + 2_000_000
            )
            if overlaps:
                events.append(
                    TimelineEvent(
                        start=min(seg.start_norm_us, other.start_norm_us),
                        end=max(seg.end_norm_us, other.end_norm_us),
                        channels=sorted({seg.channel, other.channel}),
                        kind="co_motion",
                    )
                )
    return events


@router.get("/cases/{cid}/timeline", response_model=TimelineResponse)
def get_timeline(
    cid: str,
    from_: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    bucket_s: int = 60,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TimelineResponse:
    del from_, to, bucket_s  # ignored in both modes: full coverage, no bucketing yet

    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)

        channels: list[ChannelTimeline] = []
        for ch_info in store.list_channels(cid):
            channel = ch_info["channel"]
            recs = list(store.list_recordings(cid, channel=channel))
            coverage = [
                (r.start_ts_us or 0, r.end_ts_us or 0, r.source) for r in recs if not r.deleted
            ]
            deleted_ranges = [
                (f.start_ts_us, f.end_ts_us, f.id)
                for f in store.list_deletions(cid)
                if f.channel is None or f.channel == channel
            ]
            chan_motion = store.list_motion_segments(cid, channel=channel)
            motion = [(m.start_norm_us, m.peak_score) for m in chan_motion]
            clock_model = next(
                (m for m in store.list_clock_models(cid) if m.channel == channel), None
            )
            clock = ChannelClockSummary(
                confidence=clock_model.confidence if clock_model else 0.0,
                summary=clock_model.method if clock_model else "no clock model",
            )
            channels.append(
                ChannelTimeline(
                    image_id=recs[0].image_id if recs else "",
                    channel=channel,
                    label=ch_info["label"],
                    color_token=ch_info["color_token"],
                    coverage=coverage,
                    deleted=deleted_ranges,
                    motion=motion,
                    clock=clock,
                )
            )

        markers = [
            TimelineMarker(ts_norm_us=e.ts_device_us, kind=e.kind, log_event_id=e.id, user=e.user)
            for e in store.list_log_events(cid)
            if e.kind in ("time_change", "hdd_format")
        ]
        events = _co_motion_events(store.list_motion_segments(cid))
        return TimelineResponse(channels=channels, markers=markers, events=events)

    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)

    channels = [
        _real_channel_timeline(settings.data_dir, cid, ch_info)
        for ch_info in real_list_channels(settings.data_dir, cid)
    ]
    markers = [
        TimelineMarker(ts_norm_us=e.ts_device_us, kind=e.kind, log_event_id=e.id, user=e.user)
        for e in real_pipeline.list_log_events(settings.data_dir, cid)
        if e.kind in ("time_change", "hdd_format")
    ]
    from pramaan_api.routers.analytics import real_list_motion_segments

    events = _co_motion_events(real_list_motion_segments(settings.data_dir, cid))
    return TimelineResponse(channels=channels, markers=markers, events=events)


@router.get("/cases/{cid}/clock-models", response_model=list[ClockModel])
def list_clock_models(
    cid: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[ClockModel]:
    if settings.stub_mode:
        if store.get_case(cid) is None:
            raise not_found("case", cid)
        return store.list_clock_models(cid)
    if real_store.get_case(settings.data_dir, cid) is None:
        raise not_found("case", cid)
    return real_list_clock_models(settings.data_dir, cid)


@router.post("/clock-models/{id}/override", response_model=ClockModel)
def override_clock_model(
    id: str,
    body: ClockOverrideRequest,
    user: User = Depends(require_examiner_or_admin),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf),
) -> ClockModel:
    if settings.stub_mode:
        model = store.override_clock_model(id, user.username)
        if model is None:
            raise not_found("clock_model", id)
        return model

    found = real_override_clock_model(settings.data_dir, id, user.username)
    if found is None:
        raise not_found("clock_model", id)
    case_id, model = found
    real_store.append_audit(
        settings.data_dir,
        case_id,
        actor=user.username,
        role=user.role,
        action="clock_model.overridden",
        object_type="clock_model",
        object_id=id,
        details={"reason": body.reason, "offset_us": body.offset_us},
    )
    return model
