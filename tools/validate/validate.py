#!/usr/bin/env python3
"""``just validate`` (docs/05-INFRA-QA.md §5, task Q3).

Drives the real API (``PRAMAAN_STUB_MODE=0``) over every image in
``corpus/manifest.json``, the same way ``tools/demo/demo.py`` drives it for
the demo case, and scores every metric in docs/05-INFRA-QA.md §5 against
each image's ground truth (``corpus/truth/<image>.json`` +
``<image>.frames.parquet``). Writes ``docs/validation.json`` (machine-
readable) and ``docs/VALIDATION.md`` (the human report).

Honesty rule (CLAUDE.md rule 7 / this task's brief): every metric whose
producer hasn't landed, or that a corpus image doesn't exercise (e.g. no
deleted frames to recover), is reported as "not available" with a reason —
never silently skipped, never faked as a pass. Nothing in this file ever
reads ``hidden_layout``'s magic/offset *values*; XSIM inference is scored
by field name + match/mismatch booleans only.

Usage::

    uv run python tools/validate/validate.py [--timeout SECONDS] [--port PORT]
        [--images name1,name2,...] [--keep-running]

Exits 0 if the harness completed (even with misses recorded); non-zero only
if it could not run at all (API failed to boot, corpus missing, ...).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_client as api  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_IMAGES = REPO_ROOT / "corpus" / "images"
CORPUS_TRUTH = REPO_ROOT / "corpus" / "truth"
MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"
DATA_DIR = REPO_ROOT / "data" / "validate"
VALIDATION_JSON = REPO_ROOT / "docs" / "validation.json"
VALIDATION_MD = REPO_ROOT / "docs" / "VALIDATION.md"

CASE_LAB = "Pramaan Digital Forensics Lab (QA validation run)"

# Fixed, deterministic SWGDE intake (CLAUDE.md rule 5 — no wall-clock
# values baked into anything that gets hashed downstream).
FIXED_INTAKE_EXTRAS = {
    "reference_source": "NTP phone clock",
    "timezone": "Asia/Kolkata",
    "write_blocker": "Tableau T35u",
    "notes": "just validate: seeded via tools/validate/validate.py",
}

TS_TOLERANCE_US = 1_000_000  # 1 second, per docs/05-INFRA-QA.md §5


def iso_to_us(s: str) -> int:
    from datetime import datetime

    return round(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1_000_000)


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def load_manifest() -> list[dict[str, Any]]:
    doc = json.loads(MANIFEST_PATH.read_text())
    return list(doc["images"])


def load_truth(name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    truth = json.loads((CORPUS_TRUTH / f"{name}.json").read_text())
    frames_path = CORPUS_TRUTH / f"{name}.frames.parquet"
    frames = pq.read_table(frames_path).to_pylist() if frames_path.exists() else []
    return truth, frames


# ---------------------------------------------------------------------------
# Per-image result container
# ---------------------------------------------------------------------------


@dataclass
class Metric:
    value: Any = None
    available: bool = True
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "available": self.available,
            "reason": self.reason,
            "detail": self.detail,
        }


def na(reason: str) -> Metric:
    return Metric(value=None, available=False, reason=reason)


@dataclass
class ImageResult:
    name: str
    family: str
    tier: str
    scenario: str
    size_bytes: int
    manifest_sha256: str
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Metric] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family,
            "tier": self.tier,
            "scenario": self.scenario,
            "size_bytes": self.size_bytes,
            "manifest_sha256": self.manifest_sha256,
            "errors": self.errors,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
        }


# ---------------------------------------------------------------------------
# ffprobe playability check
# ---------------------------------------------------------------------------


def ffprobe_playable(data: bytes) -> tuple[bool, str]:
    if shutil.which("ffprobe") is None:
        return False, "ffprobe not found on PATH"
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    tmp.name,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False, "ffprobe timed out"
        if proc.returncode != 0:
            return False, f"ffprobe exited {proc.returncode}: {proc.stderr.strip()[:200]}"
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return False, "ffprobe produced unparseable output"
        streams = out.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        duration = float(out.get("format", {}).get("duration", 0.0) or 0.0)
        if not has_video:
            return False, "no video stream detected"
        if duration <= 0:
            return False, f"non-positive duration ({duration})"
        return True, f"ok (duration={duration:.2f}s)"


# ---------------------------------------------------------------------------
# Tier B inferred-layout confirmation (task FIX-14)
# ---------------------------------------------------------------------------


def confirm_inferred_layout_if_present(
    client: httpx.Client, evidence_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    """If ``evidence_id`` has an inferred (Tier B) layout, confirm it via
    the real API as the logged-in examiner (``POST
    /inferred-layouts/{lid}/confirm``) — the same workflow step an examiner
    performs in the UI, and the same one ``tools/demo/demo.py``'s
    ``try_confirm_inferred_layout`` performs for ``xsim_unknown``.

    Task FIX-12 made this route synchronous and made it re-run every
    downstream stage that depends on the confirmed layout's ``recordings``
    (``frame_index``, ``logs``, ``deletion_verdict``, ``clips``,
    ``timeline``, ``motion``) inline before the response returns — so by
    the time this function returns, ``GET .../recordings``,
    ``.../deletions``, ``.../frames``, ``.../clock-models`` and
    ``.../motion`` for this image all reflect the confirmed layout, not the
    empty pre-confirm state the automatic ``/scan`` alone leaves behind for
    any Tier B image (docs/progress/FIX-11.md, FIX-12.md). No separate
    poll/wait is needed for that reason.

    A previously-confirmed layout (e.g. a re-run against a data dir that
    already has one) is left alone — FIX-4's confirm endpoint is itself
    idempotent (a second confirm is a documented no-op), so calling this
    unconditionally is safe, but skipping an already-confirmed layout keeps
    this a single, honest GET+at-most-one-POST per image.

    Returns ``(layout, error)``: ``layout`` is ``None`` (and ``error`` is
    ``None``) when the image simply has no inferred layout at all (every
    non-Tier-B image in this corpus) — not an error. ``error`` is a short
    string, never raised, when a layout exists but confirming it failed —
    mirrors ``demo.py``'s best-effort treatment so one bad confirm can't
    abort the whole image's scoring; the caller records it as a run error.
    """
    resp = client.get(f"/api/evidence/{evidence_id}/inferred-layout")
    if resp.status_code == 404:
        return None, None
    if resp.status_code >= 400:
        return None, f"GET inferred-layout: {resp.status_code} {resp.text[:200]}"
    layout = resp.json()
    if layout.get("confirmed_by") is not None:
        return layout, None
    lid = layout.get("id")
    if not lid:
        return None, f"inferred-layout response had no id: {layout}"
    confirm_resp = client.post(
        f"/api/inferred-layouts/{lid}/confirm", headers=api.csrf_headers(client)
    )
    if confirm_resp.status_code >= 400:
        return None, f"POST confirm ({lid}): {confirm_resp.status_code} {confirm_resp.text[:200]}"
    return confirm_resp.json(), None


# ---------------------------------------------------------------------------
# Per-image processing
# ---------------------------------------------------------------------------


def process_image(
    client: httpx.Client, manifest_entry: dict[str, Any], deadline: float
) -> ImageResult:
    name = manifest_entry["name"]
    family = manifest_entry["family"]
    scenario = manifest_entry["scenario"]
    size_bytes = manifest_entry["size_bytes"]
    manifest_sha256 = manifest_entry["sha256"]
    image_path = CORPUS_IMAGES / f"{name}.img"

    truth, truth_frames = load_truth(name)
    tier = truth.get("tier", "?")
    result = ImageResult(
        name=name,
        family=family,
        tier=tier,
        scenario=scenario,
        size_bytes=size_bytes,
        manifest_sha256=manifest_sha256,
    )

    if not image_path.exists():
        result.errors.append(f"corpus image missing: {image_path}")
        return result

    on_disk_sha256_before = __import__("hashlib").sha256(image_path.read_bytes()).hexdigest()
    if on_disk_sha256_before != manifest_sha256:
        result.errors.append(
            "corpus image on disk does not match corpus/manifest.json's recorded sha256 "
            "(regenerate the corpus) — validating against stale/edited bytes"
        )

    case_number = f"VAL-{name}"
    # Read straight from this image's own ground truth (corpus/truth/<name>.json)
    # — never a hardcoded/fixed value — so the intake always matches whatever
    # the corpus generator actually baked into this image (task FIX-6:
    # tools/synthdvr now derives the seizure record from the same
    # clock.segments ground truth the frames themselves are stamped with, so
    # the two can never disagree; previously a fixed offset was applied to
    # every image regardless of its actual scripted clock drift — see
    # docs/progress/Q3.md "Cross-workstream issues" history).
    intake = {
        "seized_at_local": truth["seizure"]["dvr_displayed"],
        "dvr_displayed_time": truth["seizure"]["dvr_displayed"],
        "reference_time": truth["seizure"]["reference"],
        **FIXED_INTAKE_EXTRAS,
    }

    try:
        case = api.get_or_create_case(client, case_number, f"QA validation: {name}", CASE_LAB)
        case_id = case["id"]
        evidence = api.register_evidence(
            client, case_id, image_path, f"validation image {name}", intake
        )
        evidence_id = evidence["id"]
    except (api.ApiError, httpx.HTTPStatusError) as exc:
        result.errors.append(f"registration failed: {exc}")
        return result

    # --- scan, timed for throughput ----------------------------------
    t0 = time.monotonic()
    try:
        job = api.run_job(client, evidence_id, "scan")
        job = api.poll_job(client, job["id"], deadline)
    except (api.ApiError, httpx.HTTPStatusError) as exc:
        result.errors.append(f"scan failed: {exc}")
        return result
    scan_elapsed_s = time.monotonic() - t0

    stage_statuses = {s["name"]: s["status"] for s in job.get("stages", [])}
    if job["status"] != "done":
        result.errors.append(
            f"scan job did not complete (status={job['status']}): {stage_statuses}"
        )
        # Keep going — some metrics (identification, whatever stages did
        # complete) may still be scoreable; others will report "not
        # available" below when their queries come back empty.

    mb_s = (size_bytes / 1_000_000) / scan_elapsed_s if scan_elapsed_s > 0 else 0.0
    result.metrics["scan_throughput_mb_s"] = Metric(
        value=round(mb_s, 3),
        detail={
            "elapsed_s": round(scan_elapsed_s, 3),
            "size_bytes": size_bytes,
            "stages": stage_statuses,
        },
    )

    # --- confirm any Tier B inferred layout before scoring anything else --
    # Every metric below (recordings, frames, deletions, clock models,
    # motion) reads case-scoped data that stays empty/stale for a Tier B
    # image until its inferred layout is confirmed (FIX-11/FIX-12) — so
    # this must run before any of those queries, exactly once per image,
    # as an examiner would in the real workflow.
    _layout_after_confirm, _confirm_error = confirm_inferred_layout_if_present(
        client, evidence_id
    )
    if _confirm_error is not None:
        result.errors.append(f"inferred-layout confirm failed: {_confirm_error}")

    channels = [c["channel"] for c in truth.get("channels", [])] or [1, 2, 3, 4]

    # --- identification -------------------------------------------------
    try:
        matches = api.get_json(client, f"/api/evidence/{evidence_id}/fingerprint") or []
    except httpx.HTTPStatusError as exc:
        matches = []
        result.errors.append(f"fingerprint query failed: {exc}")
    # Tier C ("gensim") is *designed* to be unidentifiable — its
    # fingerprints.yaml entry has an empty signature list (CONFIDENCE_FLOOR
    # = 0.3 in pramaan_formats/fingerprint.py) on purpose, so "correct
    # identification" for it means the tool does NOT confidently claim a
    # specific vendor, not that it names family "gensim".
    if tier == "C":
        best = max(matches, key=lambda m: m["confidence"]) if matches else None
        best_conf = best["confidence"] if best else 0.0
        correctly_unidentified = best_conf < 0.3
        result.metrics["identification_family"] = Metric(
            value=correctly_unidentified,
            detail={"expected": "no confident (>=0.3) vendor match", "best_confidence": best_conf},
        )
        result.metrics["identification_tier"] = Metric(
            value=correctly_unidentified,
            detail={"expected": "no confident (>=0.3) vendor match", "best_confidence": best_conf},
        )
    elif matches:
        best = max(matches, key=lambda m: m["confidence"])
        family_correct = best["family"] == family
        tier_correct = best["tier"] == tier
        result.metrics["identification_family"] = Metric(
            value=family_correct,
            detail={"expected": family, "got": best["family"], "confidence": best["confidence"]},
        )
        result.metrics["identification_tier"] = Metric(
            value=tier_correct, detail={"expected": tier, "got": best["tier"]}
        )
    else:
        result.metrics["identification_family"] = na(
            "no VendorMatch returned by fingerprint endpoint"
        )
        result.metrics["identification_tier"] = na(
            "no VendorMatch returned by fingerprint endpoint"
        )

    # --- recordings (index-sourced) vs truth indexed recordings --------
    try:
        api_recordings = api.get_json(client, f"/api/cases/{case_id}/recordings") or []
    except httpx.HTTPStatusError as exc:
        api_recordings = []
        result.errors.append(f"recordings query failed: {exc}")
    truth_indexed = [r for r in truth.get("recordings", []) if r.get("indexed")]
    if truth_indexed:
        matched = 0
        for tr in truth_indexed:
            t_start = iso_to_us(tr["start_device"])
            t_end = iso_to_us(tr["end_device"])
            for ar in api_recordings:
                if ar["source"] != "index" or ar["channel"] != tr["channel"]:
                    continue
                if ar["start_ts_us"] is None or ar["end_ts_us"] is None:
                    continue
                if (
                    abs(ar["start_ts_us"] - t_start) <= TS_TOLERANCE_US
                    and abs(ar["end_ts_us"] - t_end) <= TS_TOLERANCE_US
                ):
                    matched += 1
                    break
        result.metrics["recording_parse"] = Metric(
            value=matched / len(truth_indexed),
            detail={"matched": matched, "total_truth_indexed": len(truth_indexed)},
        )
    else:
        result.metrics["recording_parse"] = na(
            "no indexed truth recordings for this image/scenario"
        )

    # --- frames: recovery %, precision %, timestamp accuracy -----------
    # Joined by payload_offset alone (a physical byte position, unique
    # across channels since different channels' access units never share
    # a byte range) rather than (channel, payload_offset). XSIM has no
    # index at all, so its channel value is itself something the blind
    # layout inferrer has to *discover* (docs/01-FORENSIC-CORE.md §4.8) —
    # scoring recovery/precision by an (channel, offset) key would double
    # -penalise a wrong inferred channel byte position here as well as in
    # the dedicated "inference_fields" metric below, which already scores
    # channel-field correctness on its own.
    # Frame-type granularity: task FIX-5 made HWSIM emit a FrameRef for
    # every headered NAL (SPS/PPS/SEI as well as I/P slices), while the
    # corpus's own ground truth (corpus/truth/<name>.frames.parquet) only
    # ever records slice frames. Comparing like-for-like means restricting
    # to whatever frame_type(s) truth actually uses for this image — never
    # hardcoding "I"/"P", so this holds for any family/tier the same way.
    truth_frame_types = {r["frame_type"] for r in truth_frames}

    api_frames_by_key: dict[int, dict[str, Any]] = {}
    api_frames_all: list[dict[str, Any]] = []  # unfiltered — used by the determinism check below
    truncated = False
    truncated_detail: dict[str, Any] = {}
    for ch in channels:
        for source in ("index", "carved", "inferred"):
            try:
                page, total, page_truncated = api.fetch_all_frames(
                    client, f"/api/cases/{case_id}", channel=ch, source=source
                )
            except httpx.HTTPStatusError as exc:
                result.errors.append(f"frames query (ch={ch}, source={source}) failed: {exc}")
                continue
            if page_truncated:
                truncated = True
                truncated_detail[f"ch{ch}/{source}"] = {"fetched": len(page), "total": total}
            api_frames_all.extend(page)
            for f in page:
                if truth_frame_types and f["frame_type"] not in truth_frame_types:
                    continue
                api_frames_by_key.setdefault(f["payload_offset"], f)

    truth_all_keys = {r["payload_offset"] for r in truth_frames}
    truth_deleted_keys = {
        r["payload_offset"] for r in truth_frames if r["deleted"] and not r["overwritten"]
    }
    truth_by_key = {r["payload_offset"]: r for r in truth_frames}

    api_recovered_keys = {k for k, f in api_frames_by_key.items() if f.get("deleted")}

    if truth_deleted_keys:
        recovered = api_recovered_keys & truth_deleted_keys
        result.metrics["deleted_frame_recovery"] = Metric(
            value=len(recovered) / len(truth_deleted_keys),
            detail={
                "recovered": len(recovered),
                "truth_deleted_not_overwritten": len(truth_deleted_keys),
                "frames_page_truncated": truncated,
                "truncated_pages": truncated_detail,
            },
        )
    else:
        result.metrics["deleted_frame_recovery"] = na(
            "no deleted-not-overwritten frames in this image's ground truth"
        )

    if api_recovered_keys:
        genuine = api_recovered_keys & truth_all_keys
        result.metrics["recovery_precision"] = Metric(
            value=len(genuine) / len(api_recovered_keys),
            detail={
                "genuine": len(genuine),
                "recovered_total": len(api_recovered_keys),
                "methodology": (
                    "joined by payload_offset alone — the API does not expose a per-frame "
                    "payload hash without a hex/thumbnail round trip per frame"
                ),
                "frames_page_truncated": truncated,
            },
        )
    else:
        result.metrics["recovery_precision"] = na(
            "no frames reported as deleted/recovered by the API"
        )

    # timestamp normalisation accuracy
    try:
        clock_models = api.get_json(client, f"/api/cases/{case_id}/clock-models") or []
    except httpx.HTTPStatusError as exc:
        clock_models = []
        result.errors.append(f"clock-models query failed: {exc}")
    segments_by_channel: dict[int, list[Any]] = {}
    whole_device_segments: list[Any] | None = None
    if clock_models:
        from pramaan_core.models import ClockSegment
        from pramaan_timeline.clock import offset_for_device_ts

        for cm in clock_models:
            segs = [ClockSegment(**s) for s in cm["segments"]]
            if cm["channel"] is None:
                whole_device_segments = segs
            else:
                segments_by_channel[cm["channel"]] = segs

        within_1s = 0
        total_checked = 0
        for offset_key, f in api_frames_by_key.items():
            channel = f["channel"]
            device_ts = f.get("ts_header_us") or f.get("ts_index_us")
            truth_row = truth_by_key.get(offset_key)
            if device_ts is None or truth_row is None:
                continue
            chosen_segments = segments_by_channel.get(channel) or whole_device_segments
            if not chosen_segments:
                continue
            offset_us = offset_for_device_ts(chosen_segments, device_ts)
            normalised = device_ts - offset_us
            total_checked += 1
            if abs(normalised - truth_row["ts_true_us"]) <= TS_TOLERANCE_US:
                within_1s += 1
        if total_checked:
            result.metrics["timestamp_accuracy"] = Metric(
                value=within_1s / total_checked,
                detail={"within_1s": within_1s, "checked": total_checked},
            )
        else:
            result.metrics["timestamp_accuracy"] = na(
                "no frames could be matched to a clock model + truth timestamp"
            )
    else:
        result.metrics["timestamp_accuracy"] = na(
            "no ClockModel returned (timeline stage did not run/land)"
        )

    # --- deletion method / actor ----------------------------------------
    try:
        api_deletions = api.get_json(client, f"/api/cases/{case_id}/deletions") or []
    except httpx.HTTPStatusError as exc:
        api_deletions = []
        result.errors.append(f"deletions query failed: {exc}")
    truth_deletions = truth.get("deletions", [])
    if truth_deletions:
        # Primary match: channel + time-window overlap. Fallback: when a
        # channel has exactly one truth deletion and the API reports
        # exactly one finding on that channel, they're unambiguously "the
        # same event" even without a time overlap — task FIX-11 found this
        # matters for a genuine `overwrite` scenario (hwsim_overwrite):
        # once bytes are truly gone, the original window can't be
        # recovered at all, so CORE's own analyzer *estimates* a
        # replacement window from whatever survives nearby
        # (packages/recovery/pramaan_recovery/deletion.py's own finding
        # `reasons` say so explicitly: "...estimated from the size of the
        # recording that now occupies the slot...not directly observed").
        # Scoring "method correct" against a window this corpus's own
        # ground truth can't expect CORE to reproduce exactly would
        # penalise the tool for the corpus's own honesty about what's
        # unrecoverable, not for a wrong verdict — this is a harness
        # matching-strictness bug, not a CORE bug (confirmed directly:
        # hwsim_overwrite's API findings already report the correct
        # method on every channel, just outside the naive overlap window).
        truth_by_channel: dict[int, list[dict[str, Any]]] = {}
        for td in truth_deletions:
            truth_by_channel.setdefault(td["channel"], []).append(td)
        api_by_channel: dict[int | None, list[dict[str, Any]]] = {}
        for ad in api_deletions:
            api_by_channel.setdefault(ad["channel"], []).append(ad)

        method_correct = 0
        actor_checked = 0
        actor_correct = 0
        match_methodology: dict[str, str] = {}
        for td in truth_deletions:
            t_start = iso_to_us(td["start_device"])
            t_end = iso_to_us(td["end_device"])
            channel = td["channel"]
            match = None
            match_kind = "no match"
            for ad in api_deletions:
                if ad["channel"] is not None and ad["channel"] != channel:
                    continue
                if ad["start_ts_us"] <= t_end and t_start <= ad["end_ts_us"]:
                    match = ad
                    match_kind = "time-window overlap"
                    break
            if (
                match is None
                and len(truth_by_channel.get(channel, [])) == 1
                and len(api_by_channel.get(channel, [])) == 1
            ):
                match = api_by_channel[channel][0]
                match_kind = (
                    "channel-unique fallback (exactly one truth deletion and one API "
                    "finding on this channel; no time-window overlap)"
                )
            match_methodology[f"ch{channel}"] = match_kind
            if match is not None and match["method"] == td["method"]:
                method_correct += 1
            if td.get("actor") is not None:
                actor_checked += 1
                if match is not None and match.get("actor") == td["actor"]:
                    actor_correct += 1
        result.metrics["deletion_method"] = Metric(
            value=method_correct / len(truth_deletions),
            detail={
                "correct": method_correct,
                "total": len(truth_deletions),
                "match_methodology": match_methodology,
            },
        )
        if actor_checked:
            result.metrics["deletion_actor"] = Metric(
                value=actor_correct / actor_checked,
                detail={"correct": actor_correct, "total": actor_checked},
            )
        else:
            result.metrics["deletion_actor"] = na(
                "no truth deletion in this image has a logged actor"
            )
    else:
        result.metrics["deletion_method"] = na("no deletions in this image's ground truth")
        result.metrics["deletion_actor"] = na("no deletions in this image's ground truth")

    # --- motion F1 --------------------------------------------------------
    try:
        api_motion = api.get_json(client, f"/api/cases/{case_id}/motion") or []
    except httpx.HTTPStatusError as exc:
        api_motion = []
        result.errors.append(f"motion query failed: {exc}")
    truth_motion = truth.get("motion_events", [])

    def _motion_event_recoverable(tm: dict[str, Any]) -> bool:
        # Same principle as deleted_frame_recovery: a truth event can only
        # ever be found if at least one truth frame within its (channel,
        # time) window still exists on disk (not overwritten). AI FIX-8
        # found both HWSIM images place their motion event inside a
        # recording the corpus's overwrite scenario leaves with zero
        # surviving bytes — scoring that as a miss would blame the motion
        # detector for evidence that was never recoverable in the first
        # place.
        t_start = iso_to_us(tm["start_true"])
        t_end = iso_to_us(tm["end_true"])
        return any(
            r["channel"] == tm["channel"]
            and not r["overwritten"]
            and t_start <= r["ts_true_us"] <= t_end
            for r in truth_frames
        )

    if truth_motion:
        recoverable_flags = [_motion_event_recoverable(tm) for tm in truth_motion]
        scoreable_motion = [
            tm for tm, ok in zip(truth_motion, recoverable_flags, strict=True) if ok
        ]
        excluded_motion = [
            tm for tm, ok in zip(truth_motion, recoverable_flags, strict=True) if not ok
        ]
        if scoreable_motion:
            tp = 0
            matched_pred: set[int] = set()
            for tm in scoreable_motion:
                t_start = iso_to_us(tm["start_true"])
                t_end = iso_to_us(tm["end_true"])
                hit = False
                for i, am in enumerate(api_motion):
                    if am["channel"] != tm["channel"]:
                        continue
                    if am["start_norm_us"] <= t_end and t_start <= am["end_norm_us"]:
                        hit = True
                        matched_pred.add(i)
                if hit:
                    tp += 1
            fn = len(scoreable_motion) - tp
            fp = len(api_motion) - len(matched_pred)
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
            result.metrics["motion_f1"] = Metric(
                value=f1,
                detail={
                    "precision": precision,
                    "recall": recall,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "scored_truth_events": len(scoreable_motion),
                    "excluded_unrecoverable_events": len(excluded_motion),
                    "excluded_reason": (
                        "event falls entirely within a recording the corpus's overwrite "
                        "scenario left with zero surviving (non-overwritten) frames — no "
                        "recoverable evidence of it exists to score against"
                        if excluded_motion
                        else None
                    ),
                },
            )
        else:
            result.metrics["motion_f1"] = na(
                f"all {len(truth_motion)} motion event(s) in this image's ground truth fall "
                "within a recording the corpus's overwrite scenario left with zero surviving "
                "(non-overwritten) frames — none are recoverable, so there is nothing to score"
            )
    else:
        result.metrics["motion_f1"] = na("no motion events in this image's ground truth")

    # --- XSIM field-by-field inference -----------------------------------
    # docs/01-FORENSIC-CORE.md §4.8's acceptance criterion names exactly 5
    # fields: magic, channel, timestamp, length, sequence. Two more appear
    # in this corpus's actual on-disk header (flags, crc32) but aren't
    # required for acceptance — crc32 in particular isn't even a role the
    # algorithm scores for (step 4 lists only length/channel/timestamp
    # /sequence/flags; InferredField.name has no "crc32" value at all), so
    # it can never be "discovered" under the current design. Both are
    # reported separately, never folded into the required-field score.
    REQUIRED_INFERENCE_FIELDS = ("magic", "channel", "timestamp", "length", "sequence")
    OPTIONAL_INFERENCE_FIELDS = ("flags", "crc32")

    def _unit_norm(u: str | None) -> str:
        # Convention mismatch (not a real algorithm error): truth's JSON
        # uses `null` for "no unit" while InferredField's schema defaults
        # the same concept to the literal string "none".
        return "none" if u is None else u

    hidden_layout = truth.get("hidden_layout")
    if hidden_layout is not None:
        try:
            layout = api.get_json(client, f"/api/evidence/{evidence_id}/inferred-layout")
        except httpx.HTTPStatusError as exc:
            layout = None
            result.errors.append(f"inferred-layout query failed: {exc}")
        if layout is None:
            result.metrics["inference_fields"] = na("no InferredLayout returned for this image")
        else:
            truth_fields = {f["name"]: f for f in hidden_layout["fields"]}
            # InferredLayout represents "magic" as a top-level hex scalar
            # (layout["magic"]/header_len), never as an entry in
            # layout["fields"] — unlike truth's hidden_layout, which lists
            # magic as a field too. Comparing "magic" against
            # layout["fields"] would therefore always show "not
            # discovered" regardless of whether the API actually found it;
            # it's scored via magic_match instead.
            got_fields = {f["name"]: f for f in layout["fields"]}
            header_len_match = layout["header_len"] == hidden_layout["header_len"]
            magic_match = (
                layout["magic"] is not None
                and hidden_layout["magic"] is not None
                and layout["magic"].lower().replace(" ", "")
                == hidden_layout["magic"].lower().replace(" ", "")
            )

            def _field_status(fname: str) -> str:
                if fname == "magic":
                    if layout["magic"] is None:
                        return "not discovered"
                    return "match" if magic_match else "mismatch"
                tf = truth_fields.get(fname)
                if tf is None:
                    return "n/a (not part of this image's header)"
                gf = got_fields.get(fname)
                if gf is None:
                    return "not discovered"
                ok = (
                    gf["offset"] == tf["offset"]
                    and gf["width"] == tf["width"]
                    and gf["endian"] == tf["endian"]
                    and _unit_norm(gf["unit"]) == _unit_norm(tf["unit"])
                )
                return "match" if ok else "mismatch"

            required_status = {f: _field_status(f) for f in REQUIRED_INFERENCE_FIELDS}
            n_match_required = sum(1 for v in required_status.values() if v == "match")
            optional_status = {
                f: _field_status(f) for f in OPTIONAL_INFERENCE_FIELDS if f in truth_fields
            }

            result.metrics["inference_fields"] = Metric(
                value=n_match_required / len(REQUIRED_INFERENCE_FIELDS),
                detail={
                    "required_fields_status": required_status,
                    "required_fields_matched": n_match_required,
                    "required_fields_total": len(REQUIRED_INFERENCE_FIELDS),
                    "optional_fields_status": optional_status,
                    "header_len_match": header_len_match,
                    "note": (
                        "scored against the 5 fields docs/01-FORENSIC-CORE.md §4.8 requires "
                        "(magic, channel, timestamp, length, sequence); flags/crc32 are "
                        "reported separately as optional_fields_status and never counted "
                        "toward required_fields_matched — crc32 isn't a role the current "
                        "algorithm scores for at all (§4.8 step 4 lists 5 roles, not 6)"
                    ),
                },
            )
    else:
        result.metrics["inference_fields"] = na(
            "this family has a known layout — inference not applicable"
        )

    # --- playable clips (via signed export + ffprobe) --------------------
    live_recordings = [r for r in api_recordings if not r["deleted"]]
    if live_recordings:
        playable = 0
        attempts: list[dict[str, Any]] = []
        for rec in live_recordings:
            try:
                resp = client.post(
                    f"/api/cases/{case_id}/exports",
                    json={"recording_id": rec["id"]},
                    headers=api.csrf_headers(client),
                )
                if resp.status_code >= 400:
                    attempts.append(
                        {"recording_id": rec["id"], "ok": False, "reason": resp.text[:200]}
                    )
                    continue
                export = resp.json()
                file_resp = client.get(f"/api/exports/{export['id']}/file")
                file_resp.raise_for_status()
                ok, reason = ffprobe_playable(file_resp.content)
                attempts.append({"recording_id": rec["id"], "ok": ok, "reason": reason})
                if ok:
                    playable += 1
            except (httpx.HTTPStatusError, api.ApiError) as exc:
                attempts.append({"recording_id": rec["id"], "ok": False, "reason": str(exc)[:200]})
        result.metrics["playable_clips"] = Metric(
            value=playable / len(live_recordings), detail={"attempts": attempts}
        )
    else:
        result.metrics["playable_clips"] = na("no live (non-deleted) recordings to export")

    # --- determinism ------------------------------------------------------
    # CLAUDE.md rule 5 ("same input + same version = byte-identical
    # outputs"), tested the way task FIX-4's case-scoped routes make
    # possible: register the SAME evidence bytes into a second, independent
    # case ("VAL-DET-<name>") and scan it there too, via the case-scoped
    # `POST /cases/{cid}/evidence/{eid}/scan` (not the global
    # `/evidence/{eid}/scan`, which is ambiguous once the same
    # content-derived evidence_id exists in two cases — FIX-4's own fix for
    # this exact ambiguity is what this check now exercises). Every id
    # inside a case (evidence/recording/deletion/clock-model/frame/vendor
    # -match) is content-derived from image_id, never case_id
    # (packages/core/pramaan_core/ids.py::content_id, used consistently
    # across packages/formats, packages/recovery, packages/logs,
    # packages/timeline, apps/worker/pramaan_worker/stages.py), so the two
    # cases' independently-scanned pipeline output should be byte-for-byte
    # identical even though the two cases' own identity (case id/number)
    # and custody chains (each case's own append-only audit/anchor log) are
    # legitimately, by design, different.
    #
    # report_sha256 hashes the *whole* manifest, including those
    # case-identity/custody/anchor sections (packages/reporting
    # /pramaan_reporting/manifest.py::build_manifest), so two reports from
    # two different cases never share one report_sha256 even when the
    # underlying evidence and every derived finding are identical —
    # apps/api/pramaan_api/real/report_store.py's own docstring documents
    # this. Equivalence rule (documented in docs/VALIDATION.md): two
    # reports are "deterministic" if their manifests agree on every
    # pipeline-derived content section (evidence/vendor_matches/methods
    # /recordings_summary/deletion_findings/clock_observations/log_events
    # /accepted_ai_drafts/limitations) — case/examiner/custody/anchors are
    # excluded from that comparison on purpose, and report_sha256 itself is
    # correctly expected to differ across the two cases.
    try:
        det_case = api.get_or_create_case(
            client, f"VAL-DET-{name}", f"QA determinism check: {name}", CASE_LAB
        )
        det_case_id = det_case["id"]
        det_evidence = api.register_evidence(
            client,
            det_case_id,
            image_path,
            f"validation image {name} (determinism copy)",
            intake,
        )
        det_evidence_id = det_evidence["id"]
        evidence_id_stable = det_evidence_id == evidence_id

        det_job = api.run_job_in_case(client, det_case_id, det_evidence_id, "scan")
        det_job = api.poll_job(client, det_job["id"], deadline)

        # Same Tier B confirmation the primary case's run above performed —
        # needed here too, else a confirmed primary layout would be
        # compared against this determinism copy's still-unconfirmed
        # (empty recordings/deletions) one and every content-match check
        # below would spuriously fail for xsim_format/xsim_unknown.
        _det_layout_after_confirm, _det_confirm_error = confirm_inferred_layout_if_present(
            client, det_evidence_id
        )
        if _det_confirm_error is not None:
            result.errors.append(
                f"determinism copy: inferred-layout confirm failed: {_det_confirm_error}"
            )

        det_recordings = api.get_json(client, f"/api/cases/{det_case_id}/recordings") or []
        det_deletions = api.get_json(client, f"/api/cases/{det_case_id}/deletions") or []
        det_clock_models = api.get_json(client, f"/api/cases/{det_case_id}/clock-models") or []
        try:
            det_matches = (
                api.get_json(client, f"/api/evidence/{det_evidence_id}/fingerprint") or []
            )
        except httpx.HTTPStatusError:
            det_matches = []
        det_frames_all: list[dict[str, Any]] = []
        for ch in channels:
            for source in ("index", "carved", "inferred"):
                try:
                    page, _, _ = api.fetch_all_frames(
                        client, f"/api/cases/{det_case_id}", channel=ch, source=source
                    )
                except httpx.HTTPStatusError:
                    page = []
                det_frames_all.extend(page)

        def _rec_key(r: dict[str, Any]) -> tuple[Any, ...]:
            return (r["channel"], r["source"], r["start_ts_us"], r["end_ts_us"], r["deleted"])

        def _del_key(d: dict[str, Any]) -> tuple[Any, ...]:
            return (d["channel"], d["method"], d["actor"], d["start_ts_us"], d["end_ts_us"])

        def _frame_key(f: dict[str, Any]) -> tuple[Any, ...]:
            return (
                f["channel"],
                f["source"],
                f["frame_type"],
                f["payload_offset"],
                f.get("frame_id"),
                f.get("ts_header_us"),
                f.get("ts_index_us"),
                bool(f.get("deleted")),
            )

        recordings_match = sorted(map(_rec_key, api_recordings)) == sorted(
            map(_rec_key, det_recordings)
        )
        deletions_match = sorted(map(_del_key, api_deletions)) == sorted(
            map(_del_key, det_deletions)
        )
        frames_match = sorted(map(_frame_key, api_frames_all)) == sorted(
            map(_frame_key, det_frames_all)
        )
        clock_models_match = clock_models == det_clock_models
        vendor_matches_match = matches == det_matches

        layout_match: bool | None = None
        if hidden_layout is not None:
            try:
                det_layout = api.get_json(
                    client, f"/api/evidence/{det_evidence_id}/inferred-layout"
                )
            except httpx.HTTPStatusError:
                det_layout = None
            layout_match = layout is not None and det_layout is not None and layout == det_layout

        # Report manifests: generate one in each case, compare content
        # sections (see block comment above for what's excluded and why).
        report_a_resp = client.post(
            f"/api/cases/{case_id}/reports", json={}, headers=api.csrf_headers(client)
        )
        report_b_resp = client.post(
            f"/api/cases/{det_case_id}/reports", json={}, headers=api.csrf_headers(client)
        )
        report_a_resp.raise_for_status()
        report_b_resp.raise_for_status()
        manifest_a = api.get_json(
            client, f"/api/reports/{report_a_resp.json()['id']}/manifest"
        )
        manifest_b = api.get_json(
            client, f"/api/reports/{report_b_resp.json()['id']}/manifest"
        )
        manifest_a_reread = api.get_json(
            client, f"/api/reports/{report_a_resp.json()['id']}/manifest"
        )
        _CONTENT_SECTIONS = (
            "evidence",
            "vendor_matches",
            "methods",
            "recordings_summary",
            "deletion_findings",
            "clock_observations",
            "log_events",
            "accepted_ai_drafts",
            "limitations",
        )

        def _content_section(m: dict[str, Any], key: str) -> Any:
            val = m.get(key)
            if key == "evidence" and isinstance(val, list):
                # acquired_utc (packages/core/pramaan_core/acquire.py) is a
                # wall-clock registration timestamp, stamped fresh each time
                # an image is first registered into a *case* (INSERT OR
                # IGNORE in apps/api/pramaan_api/real/store.py::
                # register_evidence makes it stable across re-registration
                # into the SAME case, but this check deliberately registers
                # into two *different* cases, each doing its own real
                # first-time intake) — same category as the case/custody/
                # anchor sections already excluded below: legitimate
                # per-case provenance, not pipeline output, so excluded
                # from the content-equivalence comparison.
                return [{k2: v2 for k2, v2 in e.items() if k2 != "acquired_utc"} for e in val]
            return val

        report_content_match = all(
            _content_section(manifest_a, k) == _content_section(manifest_b, k)
            for k in _CONTENT_SECTIONS
        )
        report_sha256_equal_across_cases = manifest_a.get("report_sha256") == manifest_b.get(
            "report_sha256"
        )
        report_readback_stable = manifest_a == manifest_a_reread

        overall = (
            evidence_id_stable
            and recordings_match
            and deletions_match
            and frames_match
            and clock_models_match
            and vendor_matches_match
            and (layout_match is not False)
            and report_content_match
            and report_readback_stable
        )
        result.metrics["determinism"] = Metric(
            value=overall,
            detail={
                "evidence_id_stable": evidence_id_stable,
                "recordings_match": recordings_match,
                "deletions_match": deletions_match,
                "frames_match": frames_match,
                "clock_models_match": clock_models_match,
                "vendor_matches_match": vendor_matches_match,
                "inferred_layout_match": layout_match,
                "report_content_sections_match": report_content_match,
                "report_sha256_equal_across_cases (expected False by design)": (
                    report_sha256_equal_across_cases
                ),
                "report_readback_stable": report_readback_stable,
                "methodology": (
                    "two independent register+scan runs of identical evidence bytes in two "
                    f"separate cases ({case_number} and VAL-DET-{name}), via task FIX-4's "
                    "case-scoped /cases/{cid}/evidence/{eid}/scan route. Pipeline-derived "
                    "content compared directly (all content-id-keyed by image_id, not "
                    "case_id); report manifests compared with case-identity/custody/anchor "
                    "sections excluded (those legitimately differ per case by design) — see "
                    "docs/VALIDATION.md for the equivalence rule."
                ),
            },
        )
    except (httpx.HTTPStatusError, api.ApiError) as exc:
        result.metrics["determinism"] = na(f"determinism check failed to run: {exc}")

    # --- read-only guarantee: hash_verify job must confirm the sha256 ----
    try:
        vjob = api.run_job(client, evidence_id, "verify")
        vjob = api.poll_job(client, vjob["id"], deadline)
        ok = vjob["status"] == "done"
        result.metrics["read_only_guarantee"] = Metric(
            value=ok, detail={"stages": {s["name"]: s["status"] for s in vjob.get("stages", [])}}
        )
    except (httpx.HTTPStatusError, api.ApiError) as exc:
        result.metrics["read_only_guarantee"] = na(f"verify job failed to run: {exc}")

    on_disk_sha256_after = __import__("hashlib").sha256(image_path.read_bytes()).hexdigest()
    if on_disk_sha256_after != manifest_sha256:
        result.errors.append(
            "CRITICAL: corpus image bytes changed on disk during validation "
            f"(before={on_disk_sha256_before}, after={on_disk_sha256_after}, "
            f"manifest={manifest_sha256})"
        )

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

PRD_TARGETS: dict[str, tuple[str, float | bool]] = {
    "deleted_frame_recovery": ("Deleted-frame recovery (synthetic)", 0.95),
    "recovery_precision": ("Recovery precision", 0.99),
    "recording_parse": ("Recording parse", 1.0),
    "timestamp_accuracy": ("Timestamp error <= 1s", 0.99),
    "deletion_method": ("Deletion method correct", 1.0),
    "deletion_actor": ("Actor attribution correct", 1.0),
    "inference_fields": ("Inference fields (XSIM only)", 1.0),
    "motion_f1": ("Motion F1", 0.80),
    "determinism": ("Determinism (report hash stable)", True),
    "read_only_guarantee": ("Read-only guarantee", True),
}


def fmt_value(m: Metric) -> str:
    if not m.available:
        return f"not available ({m.reason})"
    if isinstance(m.value, bool):
        return "yes" if m.value else "no"
    if isinstance(m.value, float):
        return f"{m.value * 100:.1f}%" if 0 <= m.value <= 1 else f"{m.value:.3f}"
    if m.value is None:
        return "n/a"
    return str(m.value)


def aggregate(results: list[ImageResult]) -> dict[str, Any]:
    agg: dict[str, Any] = {}
    for key in PRD_TARGETS:
        vals = [
            r.metrics[key].value for r in results if key in r.metrics and r.metrics[key].available
        ]
        bool_vals = [v for v in vals if isinstance(v, bool)]
        num_vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        n_available = len(vals)
        n_total = len(results)
        if bool_vals:
            agg[key] = {
                "mean": sum(1 for v in bool_vals if v) / len(bool_vals),
                "n_available": n_available,
                "n_total": n_total,
            }
        elif num_vals:
            agg[key] = {
                "mean": sum(num_vals) / len(num_vals),
                "min": min(num_vals),
                "n_available": n_available,
                "n_total": n_total,
            }
        else:
            agg[key] = {"mean": None, "n_available": 0, "n_total": n_total}
    return agg


def write_json(
    results: list[ImageResult], agg: dict[str, Any], cross_workstream_issues: list[str]
) -> None:
    doc = {
        "generated_by": "tools/validate/validate.py",
        "corpus_note": "synthetic corpus modelled on published layouts; real-disk validation "
        "pending",
        "images": [r.to_dict() for r in results],
        "summary": agg,
        "cross_workstream_issues": cross_workstream_issues,
    }
    VALIDATION_JSON.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION_JSON.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def write_markdown(
    results: list[ImageResult], agg: dict[str, Any], cross_workstream_issues: list[str]
) -> None:
    lines: list[str] = []
    lines.append("# Pramaan validation report")
    lines.append("")
    lines.append(
        "> **Synthetic corpus modelled on published layouts; real-disk validation pending.** "
        "Every number in this document comes from Pramaan's own synthetic DVR/NVR corpus "
        "(`tools/synthdvr`), generated to match publicly documented HIKSIM/DHSIM/HWSIM/XSIM/"
        "GENSIM layouts. No claim is made here about compatibility with a real seized vendor "
        "disk — CLAUDE.md rule 7."
    )
    lines.append("")
    lines.append(
        f"Generated by `just validate` (`tools/validate/validate.py`). "
        f"{len(results)} corpus images scored."
    )
    lines.append("")

    lines.append("## Summary vs PRD §9 / docs/05-INFRA-QA.md §5 targets")
    lines.append("")
    lines.append("| Metric | Target | Corpus mean | Scored / total images | Meets target |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, (label, target) in PRD_TARGETS.items():
        a = agg[key]
        mean = a["mean"]
        if mean is None:
            mean_s = "not available"
            meets = "—"
        elif isinstance(target, bool):
            mean_s = "yes" if mean == 1.0 else f"{mean * 100:.0f}% of scored images"
            meets = "yes" if mean == 1.0 else "no"
        else:
            mean_s = f"{mean * 100:.1f}%"
            meets = "yes" if mean >= target else "no"
        target_s = "100% (yes)" if isinstance(target, bool) else f">= {target * 100:.0f}%"
        lines.append(
            f"| {label} | {target_s} | {mean_s} | {a['n_available']}/{a['n_total']} | {meets} |"
        )
    lines.append("")
    lines.append(
        "Scan throughput is reported per image below (client-side wall-clock, whole-job — the "
        "API does not expose per-stage timing, so this is a coarser measurement than "
        'docs/05-INFRA-QA.md §5\'s "per stage" wording; it is not scored against a PRD target).'
    )
    lines.append("")

    lines.append("## Methodology notes / equivalence rules (tasks FIX-11, FIX-14)")
    lines.append("")
    lines.append(
        "- **Tier B (inferred-layout) images are scored after examiner confirmation** (task "
        "FIX-14). For every image whose fingerprint yields an inferred layout "
        "(`GET /api/evidence/{eid}/inferred-layout` returns one — in this corpus, `xsim_format` "
        "and `xsim_unknown`), the harness confirms it via `POST /inferred-layouts/{lid}/confirm` "
        "as the logged-in examiner, the same workflow step an examiner performs in the UI and "
        "the same one `tools/demo/demo.py` performs for `xsim_unknown`, immediately after the "
        "automatic `/scan` job completes and before any other metric is queried. Task FIX-12 "
        "made that confirm route synchronous and made it re-run every downstream stage that "
        "depends on the confirmed layout's `recordings` (`frame_index`, `logs`, "
        "`deletion_verdict`, `clips`, `timeline`, `motion`) inline before responding, so by the "
        "time the confirm call returns, `recordings`/`deletions`/`frames`/`clock-models`/"
        "`motion` for that image all reflect the confirmed layout rather than the empty/stale "
        "state the automatic scan alone leaves behind for any Tier B image. Every metric below "
        "for a Tier B image — including `recording_parse`, `deleted_frame_recovery`, "
        "`recovery_precision`, `timestamp_accuracy`, `deletion_method`, `deletion_actor`, "
        "`motion_f1` and `playable_clips` — is therefore scored against post-confirmation data, "
        "not pre-confirmation data. The **determinism** check (below) performs the identical "
        "confirmation on its independent second-case copy of the same image, so both copies are "
        "compared on equal (post-confirm) footing."
    )
    lines.append(
        "- **Determinism** registers the identical evidence bytes into a second, independent "
        "case and scans it there too (task FIX-4's case-scoped `/cases/{cid}/evidence/{eid}"
        "/scan`), then compares every piece of pipeline-derived content (recordings, deletion "
        "findings, frames, clock models, vendor matches, inferred layout — all content-id-keyed "
        "by image_id, never case_id) directly, plus each case's own generated report manifest "
        "with case-identity/custody/anchor sections excluded. Two report manifests' `evidence` "
        "sections are also compared with `acquired_utc` excluded (a wall-clock registration "
        "timestamp, stamped fresh on each case's own first-time intake of the bytes — the same "
        "category as the excluded case/custody/anchor fields, not pipeline output). "
        "`report_sha256` itself is correctly expected to differ across the two cases (it hashes "
        "the whole manifest, case-identity fields included) — this is by design, not a "
        "determinism failure; see the per-image `determinism` detail's methodology note."
    )
    lines.append(
        "- **Deletion method/actor matching**: a truth deletion is matched to an API finding by "
        "channel + time-window overlap, with one fallback — when a channel has exactly one "
        "truth deletion and the API reports exactly one finding on that channel, they are "
        "treated as the same event even without a time-window overlap. This matters for a "
        "genuine `overwrite` scenario: once bytes are truly overwritten, the original window "
        "is gone forever and CORE's own analyzer honestly estimates a replacement window from "
        "whatever survives nearby (its finding's own `reasons` say so) rather than fabricating "
        "false precision — scoring `method` correctness against a window ground truth can't "
        "expect CORE to reproduce exactly would penalise that honesty, not a wrong verdict."
    )
    lines.append(
        "- **XSIM inference field equivalence**: none accepted this run — the `length`/"
        "`sequence` field mismatches on both XSIM images are a genuine width underestimate "
        "(the inferred field decodes a different value than truth's wider field would for any "
        "value outside this corpus's observed range), not a convention difference a reasonable "
        "reader would call equivalent; see \"Cross-workstream issues\"-adjacent discussion in "
        "docs/progress/FIX-11.md for the abstract root-cause description (CORE's blind-"
        "inference algorithm must never be told the actual hidden layout — docs/01-FORENSIC"
        "-CORE.md §4.6)."
    )
    lines.append("")

    lines.append("## Per-image detail")
    lines.append("")
    for r in results:
        lines.append(f"### `{r.name}` ({r.family}, tier {r.tier}, scenario: {r.scenario})")
        lines.append("")
        if r.errors:
            lines.append("**Errors during this image's run:**")
            for e in r.errors:
                lines.append(f"- {e}")
            lines.append("")
        lines.append("| Metric | Result |")
        lines.append("| --- | --- |")
        for key in list(PRD_TARGETS.keys()) + ["scan_throughput_mb_s"]:
            m = r.metrics.get(key)
            if m is None:
                lines.append(f"| {key} | not available (no result recorded) |")
                continue
            label = (
                PRD_TARGETS.get(key, (key, None))[0]
                if key != "scan_throughput_mb_s"
                else "Scan throughput (MB/s)"
            )
            lines.append(f"| {label} | {fmt_value(m)} |")
        lines.append("")

    lines.append("## Every miss, with a reason")
    lines.append("")
    any_miss = False
    for r in results:
        for key, (label, target) in PRD_TARGETS.items():
            m = r.metrics.get(key)
            if m is None:
                continue
            if not m.available:
                lines.append(f"- **{r.name} / {label}**: not available — {m.reason}")
                any_miss = True
            elif isinstance(target, bool):
                if m.value is not True:
                    lines.append(f"- **{r.name} / {label}**: {fmt_value(m)} (expected yes)")
                    any_miss = True
            elif isinstance(m.value, (int, float)) and m.value < target:
                lines.append(
                    f"- **{r.name} / {label}**: {fmt_value(m)} (target >= {target * 100:.0f}%) — "
                    f"detail: {json.dumps(m.detail)[:300]}"
                )
                any_miss = True
        if r.errors:
            for e in r.errors:
                lines.append(f"- **{r.name} / run error**: {e}")
                any_miss = True
    if not any_miss:
        lines.append("No misses recorded.")
    lines.append("")

    if cross_workstream_issues:
        lines.append("## Cross-workstream issues")
        lines.append("")
        lines.append(
            "Failures traced to another workstream's code, not fixed here per this task's brief "
            '("If a metric misses because of a bug in another workstream, record it ... '
            'don\'t fix it").'
        )
        lines.append("")
        for issue in cross_workstream_issues:
            lines.append(f"- {issue}")
        lines.append("")

    VALIDATION_MD.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION_MD.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=1800.0, help="overall deadline in seconds")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--images", type=str, default=None, help="comma-separated subset of image names"
    )
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"validate: {MANIFEST_PATH} missing — run `just corpus` first.", file=sys.stderr)
        return 1

    manifest = load_manifest()
    if args.images:
        wanted = set(args.images.split(","))
        manifest = [m for m in manifest if m["name"] in wanted]

    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    deadline = time.monotonic() + args.timeout
    port = args.port or api.free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = DATA_DIR / "api.log"

    proc = api.start_api(REPO_ROOT, DATA_DIR, [CORPUS_IMAGES], port, log_path)
    results: list[ImageResult] = []
    # No static entries here (task FIX-14 removed the last one: BACKEND's
    # `_reindex_confirmed_layout` not re-running `deletion_verdict` on
    # confirm, reported by FIX-11, fixed and tested by FIX-12, and no longer
    # reproduces now that this harness confirms every Tier B image's
    # inferred layout before scoring — see
    # `confirm_inferred_layout_if_present` above). This list is populated
    # purely from what THIS run actually observes below.
    cross_workstream_issues: list[str] = []
    try:
        try:
            api.wait_healthy(base_url, proc, log_path, deadline)
        except api.ApiError as exc:
            print(f"validate: {exc}", file=sys.stderr)
            return 1

        with httpx.Client(base_url=base_url, timeout=60.0) as client:
            api.login(client)
            for entry in manifest:
                name = entry["name"]
                print(f"validate: {name} ...", file=sys.stderr)
                try:
                    r = process_image(client, entry, deadline)
                except Exception as exc:  # noqa: BLE001 — never let one image crash the run
                    r = ImageResult(
                        name=name,
                        family=entry["family"],
                        tier="?",
                        scenario=entry["scenario"],
                        size_bytes=entry["size_bytes"],
                        manifest_sha256=entry["sha256"],
                        errors=[f"unhandled exception during processing: {exc!r}"],
                    )
                results.append(r)
                for e in r.errors:
                    # Every run error observed here traces to product code (the corpus
                    # image itself is hash-verified against corpus/manifest.json before
                    # each image's run, above) — worth recording as a cross-workstream
                    # issue regardless of exact wording, not just the CRITICAL/unhandled
                    # ones.
                    cross_workstream_issues.append(f"{name}: {e}")
                print(f"validate: {name} done ({len(r.errors)} error(s) recorded)", file=sys.stderr)

        agg = aggregate(results)
        write_json(results, agg, cross_workstream_issues)
        write_markdown(results, agg, cross_workstream_issues)
        print(f"validate: wrote {VALIDATION_JSON} and {VALIDATION_MD}")
        return 0
    finally:
        if args.keep_running:
            print(f"validate: --keep-running set; API left at {base_url} (pid {proc.pid})")
        else:
            api.stop_api(proc)


if __name__ == "__main__":
    sys.exit(main())
