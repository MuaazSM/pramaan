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

try:
    from pramaan_synthdvr.scenario import SEIZURE_DEVICE_OFFSET_S  # read-only reference constant
except ImportError:
    SEIZURE_DEVICE_OFFSET_S = None

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
    seizure_offset_note: str | None = None

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
            "seizure_offset_note": self.seizure_offset_note,
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
    intake = {
        "seized_at_local": truth["seizure"]["dvr_displayed"],
        "dvr_displayed_time": truth["seizure"]["dvr_displayed"],
        "reference_time": truth["seizure"]["reference"],
        **FIXED_INTAKE_EXTRAS,
    }

    # Diagnostic (not scored): the corpus's seizure record (dvr_displayed
    # vs reference — this image's own intake above) is generated by
    # tools/synthdvr as a fixed +SEIZURE_DEVICE_OFFSET_S gap on every
    # image (tools/synthdvr/pramaan_synthdvr/scenario.py), independent of
    # this image's actual baked-in clock offset
    # (truth["clock"]["segments"]). Per docs/03-AI-TIMELINE.md's
    # documented "seizure anchor" algorithm, a clock-reconstruction stage
    # correctly trusts this intake value for its most recent segment —
    # so whenever it disagrees with the image's real baked-in offset,
    # normalised-timestamp and motion metrics will legitimately miss
    # their PRD target through no fault of the reconstruction algorithm.
    if SEIZURE_DEVICE_OFFSET_S is not None and truth["clock"]["segments"]:
        baked_offset_us = truth["clock"]["segments"][-1]["offset_true_to_device_us"]
        seizure_offset_us = SEIZURE_DEVICE_OFFSET_S * 1_000_000
        if abs(baked_offset_us - seizure_offset_us) > TS_TOLERANCE_US:
            result.seizure_offset_note = (
                f"corpus seizure record implies a device offset of +{seizure_offset_us / 1e6:.0f}s "
                f"(tools/synthdvr/pramaan_synthdvr/scenario.py SEIZURE_DEVICE_OFFSET_S, applied "
                f"unconditionally to every image's seizure record) but this image's actual "
                f"baked-in clock offset (corpus/truth/{name}.json clock.segments[-1]"
                f".offset_true_to_device_us) is {baked_offset_us / 1e6:.0f}s — the two are "
                f"unrelated by corpus design, so any "
                f"seizure-anchor clock reconstruction (docs/03-AI-TIMELINE.md) will diverge from "
                f"ts_true_us here regardless of the reconstruction algorithm's own correctness."
            )

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
    api_frames_by_key: dict[int, dict[str, Any]] = {}
    truncated = False
    for ch in channels:
        for source in ("index", "carved", "inferred"):
            try:
                page = (
                    api.get_json(
                        client, f"/api/cases/{case_id}/frames", channel=ch, source=source, limit=500
                    )
                    or []
                )
            except httpx.HTTPStatusError as exc:
                result.errors.append(f"frames query (ch={ch}, source={source}) failed: {exc}")
                continue
            if len(page) >= 500:
                truncated = True
            for f in page:
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
        method_correct = 0
        actor_checked = 0
        actor_correct = 0
        for td in truth_deletions:
            t_start = iso_to_us(td["start_device"])
            t_end = iso_to_us(td["end_device"])
            match = None
            for ad in api_deletions:
                if ad["channel"] is not None and ad["channel"] != td["channel"]:
                    continue
                if ad["start_ts_us"] <= t_end and t_start <= ad["end_ts_us"]:
                    match = ad
                    break
            if match is not None and match["method"] == td["method"]:
                method_correct += 1
            if td.get("actor") is not None:
                actor_checked += 1
                if match is not None and match.get("actor") == td["actor"]:
                    actor_correct += 1
        result.metrics["deletion_method"] = Metric(
            value=method_correct / len(truth_deletions),
            detail={"correct": method_correct, "total": len(truth_deletions)},
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
    if truth_motion:
        tp = 0
        matched_pred: set[int] = set()
        for tm in truth_motion:
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
        fn = len(truth_motion) - tp
        fp = len(api_motion) - len(matched_pred)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        result.metrics["motion_f1"] = Metric(
            value=f1,
            detail={"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn},
        )
    else:
        result.metrics["motion_f1"] = na("no motion events in this image's ground truth")

    # --- XSIM field-by-field inference -----------------------------------
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
            got_fields = {f["name"]: f for f in layout["fields"]}
            per_field: dict[str, str] = {}
            n_match = 0
            for fname, tf in truth_fields.items():
                gf = got_fields.get(fname)
                if gf is None:
                    per_field[fname] = "not discovered"
                    continue
                ok = (
                    gf["offset"] == tf["offset"]
                    and gf["width"] == tf["width"]
                    and gf["endian"] == tf["endian"]
                    and gf["unit"] == tf["unit"]
                )
                per_field[fname] = "match" if ok else "mismatch"
                if ok:
                    n_match += 1
            header_len_match = layout["header_len"] == hidden_layout["header_len"]
            magic_match = (
                layout["magic"] is not None
                and hidden_layout["magic"] is not None
                and layout["magic"].lower().replace(" ", "")
                == hidden_layout["magic"].lower().replace(" ", "")
            )
            result.metrics["inference_fields"] = Metric(
                value=n_match / len(truth_fields) if truth_fields else None,
                detail={
                    "per_field_status": per_field,
                    "header_len_match": header_len_match,
                    "magic_match": magic_match,
                    "fields_total": len(truth_fields),
                    "fields_matched": n_match,
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
    # The natural way to test CLAUDE.md rule 5 ("same input + same version
    # = byte-identical outputs") over the public API is to independently
    # register + scan the *same* evidence bytes into a second case and
    # compare the resulting frames/recordings/deletions. That is blocked by
    # a discovered BACKEND bug: evidence lookup-by-id
    # (`apps/api/pramaan_api/real/store.py::_find_case_for_evidence`)
    # resolves a content-derived `evidence_id` to a case by scanning
    # `iter_case_ids()` and returning the *first* (sorted) case that has a
    # row for that id — not the case the caller actually registered it
    # under. Once the same image content is registered into two cases (as
    # this check would require), every subsequent `/evidence/{id}/...`
    # call for that id (scan, verify, fingerprint, inferred-layout) is
    # silently rerouted to whichever case sorts first, not the one the
    # caller meant. Confirmed by direct repro (two cases, same evidence
    # bytes): both scan jobs ended up scoped to the same case_id, and the
    # second job's stages all reported "skipped (already done for this
    # input)" even though it was a logically independent scan. See
    # "Cross-workstream issues" — not fixed here (apps/api is BACKEND's).
    #
    # Same-case idempotent re-run (marker-file skip, docs/02-BACKEND.md
    # §6) *is* safely testable and is a real, if weaker, signal: it
    # confirms re-running produces the same stored findings rather than
    # silently drifting or duplicating.
    try:
        rerun_job = api.run_job(client, evidence_id, "scan")
        rerun_job = api.poll_job(client, rerun_job["id"], deadline)
        rerun_recordings = api.get_json(client, f"/api/cases/{case_id}/recordings") or []
        rerun_deletions = api.get_json(client, f"/api/cases/{case_id}/deletions") or []

        def _rec_key(r: dict[str, Any]) -> tuple[Any, ...]:
            return (r["channel"], r["source"], r["start_ts_us"], r["end_ts_us"], r["deleted"])

        def _del_key(d: dict[str, Any]) -> tuple[Any, ...]:
            return (d["channel"], d["method"], d["actor"], d["start_ts_us"], d["end_ts_us"])

        stable = {_rec_key(r) for r in api_recordings} == {
            _rec_key(r) for r in rerun_recordings
        } and {_del_key(d) for d in api_deletions} == {_del_key(d) for d in rerun_deletions}
        result.metrics["determinism"] = na(
            "cannot be measured via the public API — a BACKEND evidence-resolution bug "
            "(apps/api/pramaan_api/real/store.py::_find_case_for_evidence, see "
            "Cross-workstream issues) makes registering the same evidence content into a "
            "second case unreliable. Weaker same-case idempotent re-run check: "
            f"stable={stable}, rerun_status={rerun_job['status']}"
        )
    except (httpx.HTTPStatusError, api.ApiError) as exc:
        result.metrics["determinism"] = na(
            f"cannot be measured via the public API (see reason above); same-case re-run also "
            f"failed: {exc}"
        )

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

    affected = [r.name for r in results if r.seizure_offset_note]
    if affected:
        lines.append(
            "**Known corpus-design issue affecting timestamp/motion metrics above** (see "
            '"Cross-workstream issues" for the full explanation): the synthetic corpus\'s '
            "seizure record (`dvr_displayed` vs `reference`) is generated as a fixed offset on "
            "every image, independent of that image's actual scripted clock drift. A "
            "clock-reconstruction stage that correctly follows docs/03-AI-TIMELINE.md's "
            "documented seizure-anchor algorithm will therefore diverge from `ts_true_us` on "
            "affected images through no fault of its own "
            f"logic. Affected images: {', '.join(affected)}."
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
    cross_workstream_issues: list[str] = [
        "BACKEND (apps/api/pramaan_api/real/store.py::_find_case_for_evidence): evidence "
        "lookup-by-id resolves a content-derived evidence_id to a case by scanning "
        "iter_case_ids() (sorted case dir names) and returning the first case with a matching "
        "evidence_images row — not the case the caller actually registered/scanned it under. "
        "Repro: register the same file (identical bytes -> identical content-derived "
        "evidence_id) into case A then case B, then POST /evidence/{id}/scan for each — both "
        "jobs resolve to the SAME case_id (whichever sorts first), and the second job's stages "
        "all report 'skipped (already done for this input)' even though it should be an "
        "independent scan of case B. Confirmed directly against hiksim_format.img: job1 and "
        "job2 returned job['case_id'] == the same case, though they were POSTed against two "
        "different evidence registrations in two different cases. This blocks this harness's "
        "'determinism' metric (which needs two independent scans of the same bytes) from being "
        "measured via the public API; see each image's 'determinism' row below. Not fixed here "
        "— apps/api is BACKEND's path, not QA's.",
        "BACKEND/CORE (packages/export/pramaan_export/mux.py:remux_stream_copy, via "
        "apps/api/pramaan_api/real/export_store.py:create_export -> "
        "packages/export/pramaan_export/builder.py:build_export): creating a signed export "
        "for at least one live recording of EITHER hwsim_format.img OR hwsim_overwrite.img "
        "raises an uncaught pramaan_export.mux.ExportMuxError ('ffmpeg remux failed (exit "
        "234) ... non-existing PPS 0 referenced') from POST /cases/{cid}/exports, returning "
        "HTTP 500 instead of a clean 4xx. Root cause: at least one HWSIM recording's carved "
        "frame stream starts mid-GOP without a valid SPS/PPS, which ffmpeg's stream-copy "
        "remux cannot handle. NOTE: an equivalent crash used to happen one layer up, in the "
        "scan pipeline's own 'clips' stage (apps/worker/pramaan_worker/stages.py) — that one "
        "has since been fixed to catch the error and skip the affected recording instead of "
        "crashing the whole scan job (observed across two validate.py runs on 2026-09-30: "
        "same-day, a concurrent BACKEND/CORE fix landed mid-session). The export-creation "
        "path (packages/export) still has the same unguarded call and was not covered by "
        "that fix. Effect: every HWSIM image's 'playable_clips' metric below is 0% (every "
        "export attempt 500s). Not fixed here — packages/export and apps/api are BACKEND's "
        "paths, not QA's.",
    ]
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
                if r.seizure_offset_note:
                    cross_workstream_issues.append(f"{name}: {r.seizure_offset_note}")
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
