"""FIX-6 regression test: every corpus image's seizure record must be
consistent with its own baked-in device clock.

Physically: DVR displayed time at seizure = true (reference) time at
seizure + the device's offset *at that instant* — the last (open-ended)
clock segment's ``offset_true_to_device_us``, since any scripted clock
event (e.g. ``time_change``) happens strictly before the device is seized.

Before this fix, every writer in ``tools/synthdvr/pramaan_synthdvr/writers``
computed ``seizure.dvr_displayed`` as ``reference + SEIZURE_DEVICE_OFFSET_S``
(a fixed +312 s), independent of the image's actual baked-in clock offset
(``corpus/truth/<image>.json`` ``clock.segments[-1].offset_true_to_device_us``
— 0 s for every scenario except ``hiksim_clockchange``, which bakes in
-3600 s after its scripted clock-set-back). See docs/VALIDATION.md
"Cross-workstream issues" (Q3 finding) and docs/progress/FIX-6.md.

The corpus-level tests below are cheap sanity checks against whatever
``corpus/`` already contains on disk (gitignored, populated by
``just corpus``); on a clean clone before the corpus is generated they
collect zero parametrized cases and pass trivially, matching the pattern in
``test_corpus_manifest.py``. The unit test at the bottom needs no corpus and
always runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pramaan_synthdvr.scenario import seizure_offset_us

REPO_ROOT = Path(__file__).resolve().parents[2]
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"
MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"

OWNED_FAMILIES = {"hiksim", "dhsim", "gensim", "hwsim", "xsim"}


def _truth_files() -> list[Path]:
    if not TRUTH_DIR.exists():
        return []
    return sorted(TRUTH_DIR.glob("*.json"))


@pytest.mark.parametrize("truth_path", _truth_files(), ids=lambda p: p.stem)
def test_seizure_matches_baked_in_clock_offset(truth_path: Path) -> None:
    doc = json.loads(truth_path.read_text())
    seizure = doc["seizure"]
    segments = doc["clock"]["segments"]
    assert segments, f"{truth_path.name}: no clock segments in truth"
    expected_offset_us = int(segments[-1]["offset_true_to_device_us"])

    # `reference` carries an explicit UTC offset (e.g. "+05:30");
    # `dvr_displayed` is the device's own naive local wall-clock reading —
    # attach the same tzinfo so the subtraction is well-defined.
    reference = datetime.fromisoformat(seizure["reference"])
    displayed = datetime.fromisoformat(seizure["dvr_displayed"]).replace(tzinfo=reference.tzinfo)

    actual_offset_us = round((displayed - reference).total_seconds() * 1_000_000)
    assert actual_offset_us == expected_offset_us, (
        f"{truth_path.name}: seizure.dvr_displayed - seizure.reference = "
        f"{actual_offset_us}us but this image's own device clock "
        f"(clock.segments[-1].offset_true_to_device_us) is {expected_offset_us}us"
    )


def _manifest_images() -> list[dict[str, object]]:
    if not MANIFEST_PATH.exists():
        return []
    doc = json.loads(MANIFEST_PATH.read_text())
    images = doc.get("images") or []
    return [e for e in images if e.get("family") in OWNED_FAMILIES]


@pytest.mark.parametrize("entry", _manifest_images(), ids=lambda e: str(e["name"]))
def test_manifest_seizure_matches_truth(entry: dict[str, object]) -> None:
    """`corpus/manifest.json` exposes each image's seizure record (FIX-6) —
    it must be exactly the same record `corpus/truth/<image>.json` carries,
    so `tools/demo/demo.py` and the validation harness never see a second,
    diverging copy."""
    truth_path = TRUTH_DIR / f"{entry['name']}.json"
    if not truth_path.exists():
        pytest.skip(f"{truth_path} not generated yet — run `just corpus` first")
    truth_seizure = json.loads(truth_path.read_text())["seizure"]
    assert entry.get("seizure") == truth_seizure


def test_seizure_offset_us_reads_last_segment() -> None:
    """Unit test for the helper itself (`pramaan_synthdvr.scenario`) — the
    seizure offset is whatever the *last* (open-ended) clock segment says,
    not the first, so a scripted clock event before seizure is honoured."""
    segments = [
        {"offset_true_to_device_us": 0},
        {"offset_true_to_device_us": -3_600_000_000},
    ]
    assert seizure_offset_us(segments) == -3_600_000_000
    assert seizure_offset_us([{"offset_true_to_device_us": 0}]) == 0
    assert seizure_offset_us([]) == 0
