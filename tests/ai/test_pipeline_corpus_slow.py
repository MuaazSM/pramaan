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
fingerprint -> parse_index -> carve -> frame_index -> timeline -> motion),
via the real HTTP API, against ``corpus/images/hiksim_*.img`` (task C2's
real parsers — landed; see docs/progress/C2.md/B2.md). Skips cleanly if the
corpus hasn't been generated (``just corpus`` — task Q1) or the ``hiksim``
vendor parser isn't registered yet.

**Known gap** (see docs/progress/A2.md "Fallbacks used"): task C3
(``pramaan_logs.parse_logs``) had not landed when this was written, so the
real ``logs`` pipeline stage skips gracefully and ``log_events`` stays
empty in the real pipeline today. ``hiksim_clockchange``'s accuracy bar
depends on a ``time_change`` ``LogEvent`` existing (docs §4 step 2), so
this test seeds that one row directly from ``corpus/truth``'s own
``clock.time_changes`` (exactly the row C3's parser is expected to
produce from the on-disk RATS log record) rather than skipping the
acceptance check. ``timeline_stage`` itself reads ``log_events`` exactly as
designed — once C3 lands, this happens for real, with no change here.
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
from pramaan_api.real import appdb
from pramaan_api.real.paths import case_dir as real_case_dir
from pramaan_core.frames import index_path
from pramaan_core.ids import content_id

pytestmark = pytest.mark.slow

_CORPUS_IMAGES = Path(__file__).resolve().parents[2] / "corpus" / "images"
_CORPUS_TRUTH = Path(__file__).resolve().parents[2] / "corpus" / "truth"

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
    real_settings: Any,
    real_evidence_dir: Path,
    image_name: str,
    *,
    dvr_displayed_time: str,
    reference_time: str,
    time_change: dict[str, int] | None,
) -> tuple[str, str]:
    """Registers ``corpus/images/<image_name>.img`` and runs a full scan.

    Returns ``(case_id, evidence_id)``. When ``time_change`` is given
    (``{"old_ts_us", "new_ts_us", "ts_device_us"}``), a ``time_change``
    ``LogEvent`` is seeded directly into ``log_events`` before the scan
    (see module docstring — stands in for task C3's not-yet-landed
    ``logs`` stage).
    """
    src = _corpus_image(image_name)
    assert src is not None
    dest = real_evidence_dir / f"{image_name}.img"
    shutil.copy(src, dest)

    case_resp = real_client.post(
        "/api/cases", json={"case_number": f"CR-A2-{image_name}", "title": image_name}
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
                "reference_source": "corpus/truth (tests/ai, see A2 known gap)",
                "timezone": "Asia/Kolkata",
                "make_model_label": "synthetic corpus device",
                "notes": "A2 corpus accuracy test",
            },
        },
    )
    assert ev_resp.status_code == 201, ev_resp.text
    evidence_id = ev_resp.json()["id"]

    if time_change is not None:
        guarded = appdb.case_db(real_settings.data_dir, case_id)
        row_id = content_id("le", {"image_id": evidence_id, **time_change})
        with guarded.lock:
            guarded.conn.execute(
                "INSERT INTO log_events (id, image_id, ts_device_us, kind, user, channel,"
                " details, offset) VALUES (?,?,?,?,?,?,?,?)",
                (
                    row_id,
                    evidence_id,
                    time_change["ts_device_us"],
                    "time_change",
                    "admin",
                    None,
                    json.dumps(
                        {
                            "old_ts_us": time_change["old_ts_us"],
                            "new_ts_us": time_change["new_ts_us"],
                        }
                    ),
                    0,
                ),
            )
            guarded.conn.commit()

    scan_resp = real_client.post(f"/api/evidence/{evidence_id}/scan", json={})
    assert scan_resp.status_code == 202, scan_resp.text
    job = scan_resp.json()
    assert job["status"] == "done", job

    return case_id, evidence_id


def _run_scenario(
    real_client: TestClient, real_settings: Any, real_evidence_dir: Path, image_name: str
) -> tuple[str, str]:
    truth = _load_truth(image_name)
    assert truth is not None, f"corpus/truth/{image_name}.json missing (run `just corpus`)"
    time_changes = truth["clock"]["time_changes"]
    time_change = None
    dvr_displayed_dt = datetime(2026, 3, 12, 9, 0, 0)
    if time_changes:
        tc = time_changes[0]
        time_change = {
            "old_ts_us": tc["old_ts_us"],
            "new_ts_us": tc["new_ts_us"],
            "ts_device_us": tc["new_ts_us"],
        }
        # Calibrate the seizure ClockObservation so its reconstructed
        # segments line up exactly with the corpus's own ground-truth
        # ``offset_true_to_device_us`` (docs/progress/A2.md "Decisions"):
        # the seizure applies to the most recent (post-time-change)
        # segment, whose true offset the corpus defines as
        # ``new_ts_us - old_ts_us`` (device − true, our ``offset_us``
        # convention) — zero seizure-skew of its own on top of that.
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
        real_settings,
        real_evidence_dir,
        image_name,
        dvr_displayed_time=dvr_displayed,
        reference_time=reference,
        time_change=time_change,
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
