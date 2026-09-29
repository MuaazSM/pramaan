"""Timeline (AI-owned from Wave 2 — docs/02-BACKEND.md §2, §4;
docs/03-AI-TIMELINE.md §3, §5).

BACKEND (W0.3) ships this as a thin, self-contained typed stub returning
fixture data so WEB can build the timeline screen tonight. Everything this
file needs — models, request/response shapes, fixture lookups — is either
defined right here or imported from ``pramaan_core.models`` /
``pramaan_api.fixtures.store``, so the AI workstream can replace the route
bodies (and drop the fixture import) without touching any other router.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pramaan_core.models import ClockModel
from pydantic import BaseModel, ConfigDict

from pramaan_api.deps import get_current_user, require_examiner_or_admin
from pramaan_api.errors import not_found
from pramaan_api.fixtures import store
from pramaan_api.security import User

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


@router.get("/cases/{cid}/timeline", response_model=TimelineResponse)
def get_timeline(
    cid: str,
    from_: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    bucket_s: int = 60,
    user: User = Depends(get_current_user),
) -> TimelineResponse:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    del from_, to, bucket_s  # fixture stub ignores range/bucketing, returns full coverage

    channels: list[ChannelTimeline] = []
    for ch_info in store.list_channels(cid):
        channel = ch_info["channel"]
        recs = [r for r in store.list_recordings(cid, channel=channel)]
        coverage = [(r.start_ts_us or 0, r.end_ts_us or 0, r.source) for r in recs if not r.deleted]
        deleted_ranges = [
            (f.start_ts_us, f.end_ts_us, f.id)
            for f in store.list_deletions(cid)
            if f.channel is None or f.channel == channel
        ]
        chan_motion = store.list_motion_segments(cid, channel=channel)
        motion = [(m.start_norm_us, m.peak_score) for m in chan_motion]
        clock_model = next((m for m in store.list_clock_models(cid) if m.channel == channel), None)
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

    events: list[TimelineEvent] = []
    segments = store.list_motion_segments(cid)
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
    return TimelineResponse(channels=channels, markers=markers, events=events)


@router.get("/cases/{cid}/clock-models", response_model=list[ClockModel])
def list_clock_models(cid: str, user: User = Depends(get_current_user)) -> list[ClockModel]:
    if store.get_case(cid) is None:
        raise not_found("case", cid)
    return store.list_clock_models(cid)


@router.post("/clock-models/{id}/override", response_model=ClockModel)
def override_clock_model(
    id: str, body: ClockOverrideRequest, user: User = Depends(require_examiner_or_admin)
) -> ClockModel:
    del body
    model = store.override_clock_model(id, user.username)
    if model is None:
        raise not_found("clock_model", id)
    return model
