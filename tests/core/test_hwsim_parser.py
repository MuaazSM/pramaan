"""HWSIM VendorParser tests against the real corpus
(docs/01-FORENSIC-CORE.md §5 "Tier A parse: recordings match ground truth
(channel, start/end ±1 s, offsets exact)").

``hwsim_format.img``'s ground truth has a known id-collision bug in the
generator (``tools/synthdvr/pramaan_synthdvr/writers/hwsim.py``'s
``_Recording.id`` hash omits the format scenario's "generation", so
round-0 of generation 1 and round-0 of generation 2 — post the header
reset — collide): every per-frame truth row's ``deleted``/``recording_id``
and every ``recordings[].frames``/``overwritten_frames`` summary field is
therefore unreliable for that image's colliding entries (documented in
``docs/progress/C3.md`` "Cross-workstream issues"). What's *not* affected
by the bug — because they come straight from the ``_Recording`` object's
own fields, never through the colliding id lookup — are ``start_device``/
``end_device``/``byte_ranges``/``indexed`` in ``recordings[]``, and every
frame's own intrinsic fields (``payload_offset``/``payload_len``/
``channel``/``ts_device_us``/``frame_type``/``payload_sha256``). Every
test below only reads those reliable fields, matched by ``payload_offset``
rather than by trusting the truth's own ``deleted``/grouping labels.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_formats import registry

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"


def _skip_if_missing(image: str) -> None:
    if not (IMAGES_DIR / f"{image}.img").exists():
        pytest.skip(f"corpus/images/{image}.img not generated yet — run `just corpus` first")


@pytest.mark.slow
@pytest.mark.parametrize("image", ["hwsim_format", "hwsim_overwrite"])
def test_detect_matches_truth_device_fields(image: str) -> None:
    _skip_if_missing(image)
    truth = json.loads((TRUTH_DIR / f"{image}.json").read_text())
    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        match = registry.get("hwsim").detect(r)
    assert match is not None
    assert match.family == "hwsim"
    assert match.tier == "A"
    assert match.confidence == 1.0
    assert match.model == truth["device"]["model"]
    assert match.serial == truth["device"]["serial"]


@pytest.mark.slow
@pytest.mark.parametrize("image", ["hwsim_format", "hwsim_overwrite"])
def test_list_recordings_matches_truth_live_entries(image: str) -> None:
    _skip_if_missing(image)
    truth = json.loads((TRUTH_DIR / f"{image}.json").read_text())
    live_truth = [rec for rec in truth["recordings"] if rec["indexed"]]

    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        recs = registry.get("hwsim").list_recordings(r)

    assert len(recs) == len(live_truth)
    live_truth_by_offset = {rec["byte_ranges"][0][0]: rec for rec in live_truth}
    for rec in recs:
        t = live_truth_by_offset[rec.byte_ranges[0].offset]
        assert rec.channel == t["channel"]
        assert rec.byte_ranges[0].length == t["byte_ranges"][0][1]
        assert not rec.deleted
        assert rec.source == "index"


@pytest.mark.slow
@pytest.mark.parametrize("image", ["hwsim_format", "hwsim_overwrite"])
def test_iter_frames_matches_truth_by_offset(image: str) -> None:
    """Compares by ``payload_offset`` (robust to the id-collision bug — see
    module docstring), not by filtering truth on ``deleted``."""
    _skip_if_missing(image)
    truth_frames = pq.read_table(TRUTH_DIR / f"{image}.frames.parquet").to_pylist()
    truth_by_offset = {f["payload_offset"]: f for f in truth_frames}

    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        parser = registry.get("hwsim")
        recs = parser.list_recordings(r)
        parsed = [f for rec in recs for f in parser.iter_frames(r, rec)]

    assert parsed  # sanity
    for f in parsed:
        t = truth_by_offset[f.payload_offset]
        assert f.payload_len == t["payload_len"]
        assert f.channel == t["channel"]
        assert f.ts_header_us == t["ts_device_us"]
        assert f.frame_type == t["frame_type"]
        assert f.codec == "h264"
        assert f.source == "index"
        assert not f.deleted


@pytest.mark.slow
def test_unindexed_ranges_cover_the_recoverable_deleted_region() -> None:
    """hwsim_format's round-1 (the second, fully-recoverable half of
    generation 1 — see docs/progress/C3.md "Decisions") must be entirely
    inside ``unindexed_ranges``."""
    _skip_if_missing("hwsim_format")
    truth_frames = pq.read_table(TRUTH_DIR / "hwsim_format.frames.parquet").to_pylist()
    recoverable = [f for f in truth_frames if f["deleted"] and not f["overwritten"]]
    assert recoverable

    with EvidenceReader.open(str(IMAGES_DIR / "hwsim_format.img")) as r:
        ranges = registry.get("hwsim").unindexed_ranges(r)

    for f in recoverable:
        start, end = f["payload_offset"], f["payload_offset"] + f["payload_len"]
        assert any(
            rng.offset <= start and end <= rng.offset + rng.length for rng in ranges
        ), f"recoverable frame at 0x{start:x} not covered by any unindexed range"


@pytest.mark.slow
def test_index_state_reports_capacity_fields() -> None:
    _skip_if_missing("hwsim_format")
    with EvidenceReader.open(str(IMAGES_DIR / "hwsim_format.img")) as r:
        state = registry.get("hwsim").index_state(r)
    assert state["live_channel_entry_count"] == 4
    assert state["total_allocatable"] > 0
    assert 0 <= state["available_bytes"] <= state["total_allocatable"]
