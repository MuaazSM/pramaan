"""Corpus-scale accuracy tests for task A2 (docs/03-AI-TIMELINE.md §9):

- Four-clock normalisation: ``ts_norm_us`` within ±1s of ground truth
  (``corpus/truth/*.frames.parquet``'s ``ts_true_us``) for >= 99% of frames
  on every HIKSIM image, including the mid-recording ``time_change`` on
  ``hiksim_clockchange``.
- The +37s OSD-vs-device-clock drift on ``hiksim_clockchange`` channel 2 is
  recovered (as the channel's ``ClockModel.osd_offset_us``) within ±0.5s.
- Motion triage: segment-level F1 >= 0.8 against ``corpus/truth``'s
  ``motion_events`` on every HIKSIM image.

Drives the *real* scan pipeline end to end (registration -> hash_verify ->
fingerprint -> parse_index -> carve -> frame_index -> logs ->
deletion_verdict -> clips -> timeline -> motion), via the real HTTP API,
against ``corpus/images/hiksim_*.img``/``corpus/images/hwsim_*.img`` (task
C2/C3's real parsers — landed; see docs/progress/C2.md/C3.md/B2.md). Skips
cleanly if the corpus hasn't been generated (``just corpus`` — task Q1) or
the relevant vendor parser isn't registered yet.

**FIX-8** (docs/progress/FIX-8.md): task C3's ``pramaan_logs.parse_logs``
(RATS log parsing) has now landed, and the real ``logs`` pipeline stage
parses ``hiksim_clockchange.img``'s on-disk ``time_change`` record for
real — this module no longer seeds any ``log_events`` row by hand (task
A2's own version of this file did, as a stand-in for C3 not having landed
yet; see docs/progress/A2.md "Fallbacks used" for that history). The
seizure ``ClockObservation`` intake values are still calibrated from
``corpus/truth``'s own ``clock.time_changes``/``corpus/manifest.json``'s
``seizure`` block (task FIX-6) — that's real intake data every examiner
would type in from the seizure paperwork, not a log-parsing shortcut.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from pramaan_api.real.paths import case_dir as real_case_dir
from pramaan_core.frames import index_path

pytestmark = pytest.mark.slow

_CORPUS_IMAGES = Path(__file__).resolve().parents[2] / "corpus" / "images"
_CORPUS_TRUTH = Path(__file__).resolve().parents[2] / "corpus" / "truth"
_CORPUS_MANIFEST = Path(__file__).resolve().parents[2] / "corpus" / "manifest.json"

_NORMALISATION_TOLERANCE_US = 1_000_000
_NORMALISATION_MIN_FRACTION = 0.99
_OSD_DRIFT_TOLERANCE_US = 500_000
_MOTION_MIN_F1 = 0.8


def _corpus_image(name: str) -> Path | None:
    path = _CORPUS_IMAGES / f"{name}.img"
    return path if path.is_file() else None


def _load_truth(name: str) -> dict[str, Any] | None:
    path = _CORPUS_TRUTH / f"{name}.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _load_truth_frames(name: str) -> Any | None:
    path = _CORPUS_TRUTH / f"{name}.frames.parquet"
    return pq.read_table(path) if path.is_file() else None


def _family_registered(family: str) -> bool:
    try:
        import pramaan_formats.registry as reg  # type: ignore[import-untyped]
    except ImportError:
        return False
    try:
        return reg.get(family) is not None
    except AttributeError:
        return False


def _iso_to_epoch_us(text: str) -> int:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return round(dt.timestamp() * 1_000_000)


def _register_and_scan(
    real_client: TestClient,
    real_evidence_dir: Path,
    image_name: str,
    *,
    dvr_displayed_time: str,
    reference_time: str,
    case_prefix: str = "CR-FIX8",
) -> tuple[str, str]:
    """Registers ``corpus/images/<image_name>.img`` and runs a full scan
    through the real 11-stage pipeline (including the real ``logs`` stage —
    no ``log_events`` row is seeded by hand; see module docstring).

    Returns ``(case_id, evidence_id)``.
    """
    src = _corpus_image(image_name)
    assert src is not None
    dest = real_evidence_dir / f"{image_name}.img"
    shutil.copy(src, dest)

    case_resp = real_client.post(
        "/api/cases", json={"case_number": f"{case_prefix}-{image_name}", "title": image_name}
    )
    assert case_resp.status_code == 201, case_resp.text
    case_id = case_resp.json()["id"]

    ev_resp = real_client.post(
        f"/api/cases/{case_id}/evidence",
        json={
            "path": str(dest),
            "label": image_name,
            "intake": {
                "seized_at_local": reference_time,
                "dvr_displayed_time": dvr_displayed_time,
                "reference_time": reference_time,
                "reference_source": "corpus/truth (tests/ai, real pipeline)",
                "timezone": "Asia/Kolkata",
                "make_model_label": "synthetic corpus device",
                "notes": "FIX-8 corpus accuracy test",
            },
        },
    )
    assert ev_resp.status_code == 201, ev_resp.text
    evidence_id = ev_resp.json()["id"]

    scan_resp = real_client.post(f"/api/evidence/{evidence_id}/scan", json={})
    assert scan_resp.status_code == 202, scan_resp.text
    job = scan_resp.json()
    assert job["status"] == "done", job

    return case_id, evidence_id


def _run_scenario(
    real_client: TestClient, real_settings: Any, real_evidence_dir: Path, image_name: str
) -> tuple[str, str]:
    del real_settings  # kept for signature compatibility with callers
    truth = _load_truth(image_name)
    assert truth is not None, f"corpus/truth/{image_name}.json missing (run `just corpus`)"
    time_changes = truth["clock"]["time_changes"]
    dvr_displayed_dt = datetime(2026, 3, 12, 9, 0, 0)
    if time_changes:
        tc = time_changes[0]
        # Calibrate the seizure ClockObservation so its reconstructed
        # segments line up exactly with the corpus's own ground-truth
        # ``offset_true_to_device_us`` (docs/progress/A2.md "Decisions"):
        # the seizure applies to the most recent (post-time-change)
        # segment, whose true offset the corpus defines as
        # ``new_ts_us - old_ts_us`` (device − true, our ``offset_us``
        # convention) — zero seizure-skew of its own on top of that. The
        # real ``logs`` stage (task C3) discovers the ``time_change``
        # LogEvent itself, from the image's own RATS log bytes — nothing
        # is seeded here.
        seizure_offset_us = tc["new_ts_us"] - tc["old_ts_us"]
    else:
        seizure_offset_us = 0
    # offset_us = device_ts_us - reference_ts_us (pramaan_api.real.store's
    # own naive wall-clock convention) => reference = device - offset_us.
    reference_dt = dvr_displayed_dt - timedelta(microseconds=seizure_offset_us)
    dvr_displayed = dvr_displayed_dt.strftime("%Y-%m-%dT%H:%M:%S")
    reference = reference_dt.strftime("%Y-%m-%dT%H:%M:%S")

    return _register_and_scan(
        real_client,
        real_evidence_dir,
        image_name,
        dvr_displayed_time=dvr_displayed,
        reference_time=reference,
    )


def _load_manifest_seizure(image_name: str) -> dict[str, str] | None:
    """``corpus/manifest.json``'s per-image ``seizure`` block (task FIX-6):
    ``{"dvr_displayed": "...", "reference": "..."}``, real intake values an
    examiner would type in from the seizure paperwork — used by the HWSIM
    scenarios below (no ``time_change`` to calibrate against)."""
    if not _CORPUS_MANIFEST.is_file():
        return None
    manifest = json.loads(_CORPUS_MANIFEST.read_text())
    for entry in manifest.get("images", []):
        if entry.get("name") == image_name:
            seizure = entry.get("seizure")
            return dict(seizure) if seizure else None
    return None


def _run_hwsim_scenario(
    real_client: TestClient, real_evidence_dir: Path, image_name: str
) -> tuple[str, str]:
    seizure = _load_manifest_seizure(image_name)
    assert seizure is not None, f"corpus/manifest.json has no seizure block for {image_name}"
    return _register_and_scan(
        real_client,
        real_evidence_dir,
        image_name,
        dvr_displayed_time=seizure["dvr_displayed"],
        reference_time=seizure["reference"],
    )


def _segment_f1(
    detected: list[tuple[int, int, int]], truth: list[tuple[int, int, int]]
) -> tuple[float, float, float]:
    """``(channel, start_us, end_us)`` segment-level F1 (any temporal
    overlap on the same channel counts as a match)."""
    matched: set[int] = set()
    tp = 0
    for d_ch, d_start, d_end in detected:
        for i, (t_ch, t_start, t_end) in enumerate(truth):
            if i in matched or t_ch != d_ch:
                continue
            if d_start <= t_end and t_start <= d_end:
                matched.add(i)
                tp += 1
                break
    fp = len(detected) - tp
    fn = len(truth) - len(matched)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


@pytest.mark.parametrize("image_name", ["hiksim_clean", "hiksim_format", "hiksim_clockchange"])
def test_normalisation_accuracy_against_truth(
    real_client: TestClient,
    real_settings: Any,
    real_evidence_dir: Path,
    image_name: str,
) -> None:
    if _corpus_image(image_name) is None:
        pytest.skip(f"corpus/images/{image_name}.img not present (run `just corpus`)")
    if not _family_registered("hiksim"):
        pytest.skip("pramaan_formats has no registered 'hiksim' parser yet (task C2)")
    truth_frames = _load_truth_frames(image_name)
    if truth_frames is None:
        pytest.skip(f"corpus/truth/{image_name}.frames.parquet missing (run `just corpus`)")

    case_id, evidence_id = _run_scenario(real_client, real_settings, real_evidence_dir, image_name)

    case_dir_path = real_case_dir(real_settings.data_dir, case_id)
    computed = pq.read_table(index_path(case_dir_path, evidence_id)).to_pylist()
    truth_by_offset = {row["payload_offset"]: row for row in truth_frames.to_pylist()}

    within, compared = 0, 0
    for row in computed:
        truth_row = truth_by_offset.get(row["payload_offset"])
        if truth_row is None or truth_row["overwritten"] or row["ts_norm_us"] is None:
            continue
        compared += 1
        if abs(row["ts_norm_us"] - truth_row["ts_true_us"]) <= _NORMALISATION_TOLERANCE_US:
            within += 1

    assert compared > 0, "no comparable frames (truth join produced zero rows)"
    fraction = within / compared
    assert fraction >= _NORMALISATION_MIN_FRACTION, (
        f"{image_name}: only {within}/{compared} ({fraction:.1%}) frames within "
        f"±{_NORMALISATION_TOLERANCE_US / 1e6:.0f}s of ground truth"
    )


def test_osd_drift_detected_on_clockchange_channel(
    real_client: TestClient, real_settings: Any, real_evidence_dir: Path
) -> None:
    image_name = "hiksim_clockchange"
    if _corpus_image(image_name) is None:
        pytest.skip(f"corpus/images/{image_name}.img not present (run `just corpus`)")
    if not _family_registered("hiksim"):
        pytest.skip("pramaan_formats has no registered 'hiksim' parser yet (task C2)")

    case_id, _evidence_id = _run_scenario(
        real_client, real_settings, real_evidence_dir, image_name
    )
    resp = real_client.get(f"/api/cases/{case_id}/clock-models")
    assert resp.status_code == 200, resp.text
    models = resp.json()
    ch2 = next((m for m in models if m["channel"] == 2), None)
    assert ch2 is not None, "no ClockModel for channel 2"
    assert ch2["osd_offset_us"] is not None, "channel 2 has no OSD offset (OCR found nothing)"
    drift_s = ch2["osd_offset_us"] / 1_000_000
    assert abs(drift_s - 37.0) <= _OSD_DRIFT_TOLERANCE_US / 1_000_000, (
        f"channel 2 OSD drift {drift_s:.2f}s not within "
        f"±{_OSD_DRIFT_TOLERANCE_US / 1e6:.1f}s of the true +37.0s"
    )


@pytest.mark.parametrize("image_name", ["hiksim_clean", "hiksim_format", "hiksim_clockchange"])
def test_motion_segment_f1_against_truth(
    real_client: TestClient,
    real_settings: Any,
    real_evidence_dir: Path,
    image_name: str,
) -> None:
    if _corpus_image(image_name) is None:
        pytest.skip(f"corpus/images/{image_name}.img not present (run `just corpus`)")
    if not _family_registered("hiksim"):
        pytest.skip("pramaan_formats has no registered 'hiksim' parser yet (task C2)")
    truth = _load_truth(image_name)
    assert truth is not None

    case_id, _evidence_id = _run_scenario(
        real_client, real_settings, real_evidence_dir, image_name
    )
    resp = real_client.get(f"/api/cases/{case_id}/motion")
    assert resp.status_code == 200, resp.text
    detected = [(m["channel"], m["start_norm_us"], m["end_norm_us"]) for m in resp.json()]
    truth_segments = [
        (
            e["channel"],
            _iso_to_epoch_us(e["start_true"]),
            _iso_to_epoch_us(e["end_true"]),
        )
        for e in truth["motion_events"]
    ]

    precision, recall, f1 = _segment_f1(detected, truth_segments)
    assert f1 >= _MOTION_MIN_F1, (
        f"{image_name}: motion F1={f1:.2f} (precision={precision:.2f}, recall={recall:.2f}), "
        f"detected={detected}, truth={truth_segments}"
    )


# --------------------------------------------------------------------------
# HWSIM motion triage (FIX-8): decode needs SPS/PPS (FIX-5 gave HWSIM its
# own SPS/PPS/SEI FrameRefs, one per physical NAL) — see
# ``pramaan_analytics.motion._build_decode_groups``/``_carved_decode_runs``,
# fixed by this task to include parameter-set rows in the ffmpeg decode
# *input* while still scoring/timestamping slice (I/P) rows only.
# --------------------------------------------------------------------------


def _recoverable_truth_motion_events(image_name: str) -> list[dict[str, Any]]:
    """``truth["motion_events"]`` filtered to events with at least one
    surviving (not physically overwritten) truth frame on the same channel
    within the event's own time window.

    HWSIM's ``format``/``overwrite`` scenarios can destroy a channel's
    *entire* oldest recording with zero surviving bytes (see
    docs/progress/C3.md "Decisions": "two HWSIM scenarios' deletion time
    ranges honestly can't hit ±5s ... 100% physically overwritten with zero
    surviving bytes"). A motion event placed inside such a recording cannot
    be recovered from any byte on disk — CLAUDE.md rule 1 forbids
    fabricating a detection for it — so it is excluded here the same way
    ``test_normalisation_accuracy_against_truth`` already excludes
    ``truth_row["overwritten"]`` frames from its own comparison. See
    docs/progress/FIX-8.md "Cross-workstream issues" for the corpus-design
    root cause (flagged for tools/synthdvr, not fixed here)."""
    truth = _load_truth(image_name)
    truth_frames = _load_truth_frames(image_name)
    if truth is None or truth_frames is None:
        return []
    frames = truth_frames.to_pylist()
    recoverable: list[dict[str, Any]] = []
    for event in truth["motion_events"]:
        start_us = _iso_to_epoch_us(event["start_true"])
        end_us = _iso_to_epoch_us(event["end_true"])
        window = [
            f
            for f in frames
            if f["channel"] == event["channel"] and start_us <= f["ts_true_us"] <= end_us
        ]
        if window and any(not f["overwritten"] for f in window):
            recoverable.append(event)
    return recoverable


@pytest.mark.parametrize("image_name", ["hwsim_format", "hwsim_overwrite"])
def test_motion_segment_f1_against_truth_hwsim(
    real_client: TestClient,
    real_evidence_dir: Path,
    image_name: str,
) -> None:
    if _corpus_image(image_name) is None:
        pytest.skip(f"corpus/images/{image_name}.img not present (run `just corpus`)")
    if not _family_registered("hwsim"):
        pytest.skip("pramaan_formats has no registered 'hwsim' parser yet (task C3)")
    truth = _load_truth(image_name)
    assert truth is not None
    recoverable_events = _recoverable_truth_motion_events(image_name)
    if not recoverable_events:
        pytest.skip(
            f"{image_name}: every ground-truth motion event sits in a recording that is "
            "100% physically overwritten (no surviving bytes) — nothing forensically "
            "recoverable to score F1 against; see docs/progress/FIX-8.md "
            "'Cross-workstream issues'"
        )

    case_id, _evidence_id = _run_hwsim_scenario(real_client, real_evidence_dir, image_name)
    resp = real_client.get(f"/api/cases/{case_id}/motion")
    assert resp.status_code == 200, resp.text
    detected = [(m["channel"], m["start_norm_us"], m["end_norm_us"]) for m in resp.json()]
    truth_segments = [
        (e["channel"], _iso_to_epoch_us(e["start_true"]), _iso_to_epoch_us(e["end_true"]))
        for e in recoverable_events
    ]

    precision, recall, f1 = _segment_f1(detected, truth_segments)
    assert f1 >= _MOTION_MIN_F1, (
        f"{image_name}: motion F1={f1:.2f} (precision={precision:.2f}, recall={recall:.2f}), "
        f"detected={detected}, recoverable truth={truth_segments}"
    )


def test_motion_triage_decodes_hwsim_live_recording_without_error(
    real_client: TestClient,
    real_settings: Any,
    real_evidence_dir: Path,
) -> None:
    """A narrower regression check for the FIX-8 root cause itself: the
    ``motion`` stage must actually decode *something* on a HWSIM channel
    with live footage (not just silently produce zero segments because
    every per-NAL slice payload failed to decode without its SPS/PPS).
    ``motion_score`` is a Parquet-only column (docs/03-AI-TIMELINE.md §3),
    not on the ``FrameRef`` API contract, so this reads the frame index
    directly rather than the frames API, the same way
    ``test_normalisation_accuracy_against_truth`` reads ``ts_norm_us``."""
    image_name = "hwsim_format"
    if _corpus_image(image_name) is None:
        pytest.skip(f"corpus/images/{image_name}.img not present (run `just corpus`)")
    if not _family_registered("hwsim"):
        pytest.skip("pramaan_formats has no registered 'hwsim' parser yet (task C3)")

    case_id, evidence_id = _run_hwsim_scenario(real_client, real_evidence_dir, image_name)
    case_dir_path = real_case_dir(real_settings.data_dir, case_id)
    rows = pq.read_table(index_path(case_dir_path, evidence_id)).to_pylist()
    ch1_slices = [r for r in rows if r["channel"] == 1 and r["frame_type"] in ("I", "P")]
    assert ch1_slices, f"no channel-1 slice frames indexed for {image_name}"
    scored = [r for r in ch1_slices if r["motion_score"] is not None]
    assert scored, (
        f"no channel-1 slice frame on {image_name} evidence {evidence_id} got a "
        "motion_score — the decoder likely failed on every access unit (missing SPS/PPS "
        "in the ffmpeg input; see docs/progress/FIX-8.md)"
    )
