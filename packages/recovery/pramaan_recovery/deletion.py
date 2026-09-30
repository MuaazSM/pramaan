"""Deletion verdict (docs/01-FORENSIC-CORE.md §4.10).

``detect_deletions`` is the B2 integration-contract entry point
(docs/progress/B2.md "Integration contract"):

    detect_deletions(*, image_id, recordings, frames, log_events) -> list[DeletionFinding]

It only sees what B2's pipeline persists — ``recordings`` (every
``Recording`` the caller knows about for this image; each carries its own
``deleted`` flag), every ``FrameRef`` found by any stage (live *and*
carved — carved frames carry ``deleted=True``), and ``LogEvent``s. There
is no family-specific ``index_state()`` here, so every rule below is
expressed purely in terms of those three generic inputs — deliberately,
since that's what keeps this module usable for a family with a live
vendor parser (HIKSIM/DHSIM/HWSIM, whose ``recordings`` are always
``source="index", deleted=False`` per ``VendorParser.list_recordings``'s
own contract) *and* a Tier-B inferred one (XSIM, whose caller —
apps/worker's ``parse_inferred_layout``, FIX-7 — has no native index at
all and so hands this module ``recordings`` for *every* discovered run on
a channel, live and already-deleted mixed together, ``source="inferred"``)
behind the same call. Every "live recording" computation below therefore
explicitly filters to ``not r.deleted`` rather than assuming the list it
was given contains only those (FIX-7: that assumption held for every
native-parser family but silently broke XSIM's format-vs-expiry
classification, since an older deleted run's own start was being read as
"the earliest live recording").

Two independent signals produce a finding for a channel:

1. **Direct evidence** (``_channel_evidence_finding``): deleted frames were
   actually recovered (via a live index confirming they're no longer
   referenced, or via carving). Grouped into continuous runs (gap <= 5 s,
   docs/01-FORENSIC-CORE.md §4.10) to classify ``format`` vs ``expiry`` by
   whether an ``hdd_format`` log event correlates, else by whether the
   live index resumes immediately (expiry: a rolling FIFO prune, no
   downtime) or only after a large gap (format: an admin action, even
   without log evidence — e.g. HWSIM, which has no documented log format
   at all, docs/01-FORENSIC-CORE.md §4.9). When a channel's disk history
   holds *more than one* deleted run before the live recording (observed
   on ``xsim_format``: a single format wipe can leave more than one
   gap-separated run of recoverable bytes behind), the reported window
   spans every recovered deleted frame on that channel, not just the run
   nearest the live boundary — real, already-available evidence, not an
   extrapolation — while the gap used to pick format-vs-expiry still comes
   from the run nearest the live boundary specifically.
2. **Wrap-around inference** (``_wraparound_finding``): a channel with *no*
   recoverable deleted frames at all, but whose live recordings show the
   physically lowest-offset one is *not* the chronologically earliest —
   the literal §4.10 "overwrite" signature. Since nothing of the
   overwritten data survives to carve, its time range is estimated (not
   observed) from the size of the recording that now occupies its slot and
   the point the surviving live timeline resumes; this is flagged clearly
   in ``reasons`` and given a lower confidence, never presented as directly
   observed.

A single ``format`` action typically wipes every channel at once. Where
several channels' findings correlate to the *same* ``hdd_format`` log event
but a physically-overwritten prefix left one channel's earliest evidence
later than another's (docs/progress/Q1.md "Decisions": the corpus
overwrites only a *prefix* of the reused region), ``start_ts_us`` is
sharpened to the earliest evidence observed on *any* corroborating channel
— evidence found on one channel legitimately informing the same device-wide
event's start time on another, never fabricating a value with no
observed grounding anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pramaan_core.ids import content_id
from pramaan_core.models import DeletionFinding, FrameRef, LogEvent, Recording

#: docs/01-FORENSIC-CORE.md §4.10: "Group deleted frames per channel into
#: continuous ranges (gap <= 5 s)".
RUN_GAP_US = 5_000_000

#: A live recording resuming within this long of the last recovered frame
#: reads as continuous (FIFO "expiry"), not a paused/admin "format" action.
EXPIRY_CONTINUITY_US = 30_000_000

#: How far an ``hdd_format``/``time_change`` log event may sit from a
#: deletion window and still be treated as evidence for it
#: (docs/01-FORENSIC-CORE.md §4.10: "within ± 10 min" for hdd_format).
LOG_CORRELATION_WINDOW_US = 30 * 60 * 1_000_000
TIME_CHANGE_CAUTION_WINDOW_US = 10 * 60 * 1_000_000

_BASE_CONFIDENCE = 0.5
_HDD_FORMAT_BOOST = 0.2
_TIME_CHANGE_PENALTY = 0.1
_WRAPAROUND_BASE_CONFIDENCE = 0.4
_MAX_CONFIDENCE = 0.99


@dataclass
class _RawFinding:
    channel: int
    start_ts_us: int
    end_ts_us: int
    method: str
    actor: str | None
    action_ts_us: int | None
    frames_recovered: int
    bytes_recovered: int
    confidence: float
    reasons: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


def detect_deletions(
    *,
    image_id: str,
    recordings: list[Recording],
    frames: list[FrameRef],
    log_events: list[LogEvent],
) -> list[DeletionFinding]:
    channels = sorted(
        {r.channel for r in recordings} | {f.channel for f in frames if f.channel is not None}
    )

    # A "deletion" is only a meaningful concept for an image that
    # demonstrably has a live-index concept at all (at least one recording
    # currently referenced by *some* channel's index). A pure Tier-C image
    # with no index whatsoever (GENSIM) has every carved frame marked
    # ``deleted=True`` by the generic carver's own convention (it has no
    # index to say otherwise) — that is *not* evidence of an actual
    # deletion, so Pass A is skipped entirely for an image with no live
    # recordings anywhere (docs/01-FORENSIC-CORE.md §4.10 assumes an index
    # existed to be reset/freed/wrapped).
    has_index_concept = bool(recordings)

    raw: dict[int, _RawFinding] = {}
    if has_index_concept:
        for ch in channels:
            rf = _channel_evidence_finding(ch, recordings, frames, log_events)
            if rf is not None:
                raw[ch] = rf
        _align_shared_format_events(raw)

    for ch in channels:
        if ch in raw:
            continue
        wf = _wraparound_finding(ch, recordings)
        if wf is not None:
            raw[ch] = wf

    findings = [_finalize(image_id, rf) for rf in raw.values()]
    return sorted(findings, key=lambda f: ((f.channel or 0), f.start_ts_us, f.id))


def _group_runs(items: list[FrameRef], gap_us: int) -> list[list[FrameRef]]:
    runs: list[list[FrameRef]] = []
    cur: list[FrameRef] = []
    prev_ts: int | None = None
    for f in items:
        assert f.ts_header_us is not None
        if prev_ts is not None and f.ts_header_us - prev_ts > gap_us:
            runs.append(cur)
            cur = []
        cur.append(f)
        prev_ts = f.ts_header_us
    if cur:
        runs.append(cur)
    return runs


def _nearest_log(
    log_events: list[LogEvent], kind: str, window_start: int, window_end: int
) -> LogEvent | None:
    candidates = [
        e
        for e in log_events
        if e.kind == kind
        and window_start - LOG_CORRELATION_WINDOW_US <= e.ts_device_us
        <= window_end + LOG_CORRELATION_WINDOW_US
    ]
    if not candidates:
        return None
    mid = (window_start + window_end) // 2
    return min(candidates, key=lambda e: abs(e.ts_device_us - mid))


def _nearby_time_change(log_events: list[LogEvent], start_ts: int, end_ts: int) -> LogEvent | None:
    for e in log_events:
        if e.kind != "time_change":
            continue
        lo = start_ts - TIME_CHANGE_CAUTION_WINDOW_US
        hi = end_ts + TIME_CHANGE_CAUTION_WINDOW_US
        if lo <= e.ts_device_us <= hi:
            return e
    return None


def _channel_evidence_finding(
    channel: int,
    recordings: list[Recording],
    frames: list[FrameRef],
    log_events: list[LogEvent],
) -> _RawFinding | None:
    del_frames = sorted(
        (f for f in frames if f.channel == channel and f.deleted and f.ts_header_us is not None),
        key=lambda f: (f.ts_header_us, f.payload_offset),
    )
    if not del_frames:
        return None
    runs = _group_runs(del_frames, RUN_GAP_US)
    # "Live" here means *currently referenced by the index*
    # (``Recording.deleted is False`` — docs/01-FORENSIC-CORE.md §4.10's own
    # rules are all phrased in terms of the live index). For a native
    # vendor parser (HIKSIM/DHSIM/HWSIM) every ``Recording`` this module
    # ever receives already satisfies that (``VendorParser.list_recordings``'s
    # contract: always ``deleted=False``), so this filter is a no-op there.
    # It is *not* a no-op for a Tier B/inferred image (XSIM): the caller
    # that turns an ``InferredParser``'s frame stream into ``Recording``s
    # (apps/worker's ``parse_inferred_layout``) has no native index at all,
    # so it emits one ``Recording`` per discovered run on a channel —
    # older, no-longer-current runs included, marked ``deleted=True`` —
    # in the *same* list this function receives as ``recordings``. Using
    # that list unfiltered previously picked an older, already-deleted
    # run's own start as "the earliest live recording", producing a
    # negative or near-zero gap to the very evidence being classified and
    # misreading a device-wide format wipe as continuous FIFO expiry.
    live = [r for r in recordings if r.channel == channel and not r.deleted]
    earliest_live_start = min(
        (r.start_ts_us for r in live if r.start_ts_us is not None), default=None
    )
    # The run immediately preceding the earliest live recording carries the
    # evidence used to decide the gap-based method (format vs. expiry) and
    # anchors ``end_ts``/log correlation, but when the channel's disk
    # history holds more than one deleted run before that live recording
    # (observed on ``xsim_format``: a device-wide format wipes *every*
    # older run at once, not just the one immediately before the live
    # recording), the deletion's reported window should cover every
    # recovered deleted frame on this channel, not just the last run —
    # nothing here is fabricated, it is evidence this function already has.
    last_run = runs[-1]
    start_ts = del_frames[0].ts_header_us
    end_ts = last_run[-1].ts_header_us
    assert start_ts is not None and end_ts is not None

    if len(runs) > 1:
        reasons: list[str] = [
            f"{len(del_frames)} deleted frame(s) recovered on channel {channel} across "
            f"{len(runs)} separate runs (gap > {RUN_GAP_US / 1_000_000:.0f}s between them), "
            f"spanning payload offsets {del_frames[0].payload_offset}-"
            f"{del_frames[-1].payload_offset} — treated as one deletion event since nothing "
            "survives to show a live recording in between them",
        ]
    else:
        reasons = [
            f"{len(last_run)} deleted frame(s) recovered on channel {channel} spanning payload "
            f"offsets {last_run[0].payload_offset}-{last_run[-1].payload_offset}",
        ]

    method: str
    actor: str | None
    action_ts_us: int | None
    confidence: float

    window_end = earliest_live_start if earliest_live_start is not None else end_ts
    hdd_format_evt = _nearest_log(log_events, "hdd_format", end_ts, window_end)
    if hdd_format_evt is not None:
        method = "format"
        actor = hdd_format_evt.user
        action_ts_us = hdd_format_evt.ts_device_us
        confidence = _BASE_CONFIDENCE + _HDD_FORMAT_BOOST
        reasons.append(
            f"hdd_format log event {hdd_format_evt.id} at offset {hdd_format_evt.offset} "
            f"(ts={hdd_format_evt.ts_device_us}) correlates with this deletion"
        )
    else:
        gap = (earliest_live_start - end_ts) if earliest_live_start is not None else None
        if gap is not None and gap <= EXPIRY_CONTINUITY_US:
            method = "expiry"
            action_ts_us = earliest_live_start
            confidence = _BASE_CONFIDENCE
            reasons.append(
                f"live recording on channel {channel} resumes {gap / 1_000_000:.2f}s after the "
                "last recovered frame with no hdd_format log evidence — reads as index entries "
                "freed from the oldest end (expiry), not an admin action"
            )
            # An automatic space-reclaim isn't logged as `hdd_format`, but a
            # `logout`-kind event shortly after is the best available proxy
            # for who/what was responsible (docs/01-FORENSIC-CORE.md §4.10
            # only names this correlation for hdd_format explicitly; this is
            # the same idea applied to the weaker expiry signal, at a lower
            # confidence than the hdd_format-based boost).
            logout_evt = _nearest_log(log_events, "logout", end_ts, end_ts)
            if logout_evt is not None:
                actor = logout_evt.user
                confidence += _HDD_FORMAT_BOOST / 2
                reasons.append(
                    f"logout log event {logout_evt.id} at offset {logout_evt.offset} "
                    f"(ts={logout_evt.ts_device_us}) shortly follows this deletion — treated as a "
                    "weaker proxy for the responsible actor than an explicit hdd_format record"
                )
            else:
                actor = None
        else:
            method = "format"
            actor = None
            action_ts_us = None
            confidence = _BASE_CONFIDENCE
            if gap is not None:
                reasons.append(
                    f"a {gap / 1_000_000:.0f}s gap separates the last recovered frame from the "
                    f"next live recording on channel {channel}, with no log evidence to name an "
                    "actor (this family has no documented log format, or none survived)"
                )
            else:
                reasons.append(
                    f"no live recording remains on channel {channel}; recording ends abruptly "
                    "with no log evidence to name an actor"
                )

    tc = _nearby_time_change(log_events, start_ts, end_ts)
    if tc is not None:
        reasons.append(
            f"a time_change log event ({tc.id}) is near this range; recovered timestamps may not "
            "be continuous with the device's earlier clock"
        )
        confidence -= _TIME_CHANGE_PENALTY

    confidence = max(0.0, min(_MAX_CONFIDENCE, confidence))
    return _RawFinding(
        channel=channel,
        start_ts_us=start_ts,
        end_ts_us=end_ts,
        method=method,
        actor=actor,
        action_ts_us=action_ts_us,
        frames_recovered=len(del_frames),
        bytes_recovered=sum(f.payload_len for f in del_frames),
        confidence=confidence,
        reasons=reasons,
        evidence_refs=[f.frame_id for f in del_frames],
    )


def _align_shared_format_events(raw: dict[int, _RawFinding]) -> None:
    """When several channels' ``format`` findings correlate to the same
    ``hdd_format`` log event, a channel whose own earliest recoverable
    frame is later (because more of its prefix was physically overwritten
    — docs/progress/Q1.md "Decisions") borrows the earliest start actually
    observed on any corroborating channel, since a single format action
    starts at the same instant for every channel it affects."""
    groups: dict[int, list[int]] = {}
    for ch, rf in raw.items():
        if rf.method == "format" and rf.action_ts_us is not None:
            groups.setdefault(rf.action_ts_us, []).append(ch)
    for action_ts, chans in groups.items():
        if len(chans) < 2:
            continue
        shared_start = min(raw[c].start_ts_us for c in chans)
        for c in chans:
            if raw[c].start_ts_us > shared_start:
                raw[c] = replace(
                    raw[c],
                    start_ts_us=shared_start,
                    reasons=[
                        *raw[c].reasons,
                        "start time aligned to the earliest evidence observed on a channel "
                        f"sharing the same format action (action_ts_us={action_ts})",
                    ],
                )


def _wraparound_finding(channel: int, recordings: list[Recording]) -> _RawFinding | None:
    # Only currently-live recordings define "physically lowest offset isn't
    # chronologically earliest" — the same live/deleted distinction
    # ``_channel_evidence_finding`` applies (see its comment): a caller that
    # also hands this module already-deleted ``Recording``s (e.g. an
    # inferred/XSIM image's older runs) must not have them corrupt the
    # live-recording ordering this signal depends on.
    live = sorted(
        (
            r
            for r in recordings
            if r.channel == channel and not r.deleted and r.start_ts_us is not None
        ),
        key=lambda r: r.start_ts_us,  # type: ignore[arg-type,return-value]
    )
    if len(live) < 2:
        return None
    by_offset = sorted(
        live, key=lambda r: (r.byte_ranges[0].offset if r.byte_ranges else 0)
    )
    if by_offset[0].id == live[0].id:
        return None  # physically-earliest is also chronologically-earliest: no wrap-around

    newest_in_oldest_slot = by_offset[0]
    duration_us: int | None = None
    nio_start, nio_end = newest_in_oldest_slot.start_ts_us, newest_in_oldest_slot.end_ts_us
    if nio_start is not None and nio_end is not None:
        duration_us = nio_end - nio_start

    end_est = live[0].start_ts_us
    assert end_est is not None
    start_est = end_est - duration_us if duration_us else end_est
    offset_str = (
        str(by_offset[0].byte_ranges[0].offset) if by_offset[0].byte_ranges else "unknown"
    )
    reasons = [
        f"channel {channel}'s physically lowest-offset live recording (offset {offset_str}) is "
        f"the chronologically *newest* one (start {newest_in_oldest_slot.start_ts_us}), while "
        "chronologically earlier live recordings sit at higher byte offsets — a circular-buffer "
        "wrap-around signature",
        "the recording that previously occupied this slot is fully overwritten; no bytes survive "
        "to recover its own timestamps, so start/end are estimated from the size of the recording "
        "that now occupies the slot and where the surviving live timeline resumes, not directly "
        "observed",
    ]
    return _RawFinding(
        channel=channel,
        start_ts_us=start_est,
        end_ts_us=end_est,
        method="overwrite",
        actor=None,
        action_ts_us=newest_in_oldest_slot.start_ts_us,
        frames_recovered=0,
        bytes_recovered=0,
        confidence=_WRAPAROUND_BASE_CONFIDENCE,
        reasons=reasons,
        evidence_refs=[r.id for r in live],
    )


def _finalize(image_id: str, rf: _RawFinding) -> DeletionFinding:
    fid = content_id(
        "del",
        {
            "image_id": image_id,
            "channel": rf.channel,
            "start_ts_us": rf.start_ts_us,
            "method": rf.method,
        },
    )
    return DeletionFinding(
        id=fid,
        image_id=image_id,
        channel=rf.channel,
        start_ts_us=rf.start_ts_us,
        end_ts_us=rf.end_ts_us,
        method=rf.method,  # type: ignore[arg-type]
        actor=rf.actor,
        action_ts_us=rf.action_ts_us,
        frames_recovered=rf.frames_recovered,
        bytes_recovered=rf.bytes_recovered,
        confidence=rf.confidence,
        reasons=rf.reasons,
        evidence_refs=rf.evidence_refs,
    )


def summarize_findings(findings: list[DeletionFinding]) -> str:
    """A human-readable per-image summary (docs/01-FORENSIC-CORE.md §4.10),
    e.g. "3 deletion events, 41 min of footage recovered across 4
    channels"."""
    if not findings:
        return "No deletions found."
    channels = {f.channel for f in findings if f.channel is not None}
    total_us = sum(max(0, f.end_ts_us - f.start_ts_us) for f in findings)
    minutes = total_us / 1_000_000 / 60
    n = len(findings)
    return (
        f"{n} deletion event{'s' if n != 1 else ''}, {minutes:.0f} min of footage recovered "
        f"across {len(channels)} channel{'s' if len(channels) != 1 else ''}"
    )
