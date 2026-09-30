"""HIKSIM VendorParser tests against the real corpus
(docs/01-FORENSIC-CORE.md §5 "Tier A parse: recordings match ground truth
(channel, start/end ±1 s, offsets exact)").
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

ONE_SECOND_US = 1_000_000


def _corpus_available(image: str) -> bool:
    return (IMAGES_DIR / f"{image}.img").exists() and (TRUTH_DIR / f"{image}.json").exists()


def _skip_if_missing(image: str) -> None:
    if not _corpus_available(image):
        pytest.skip(f"corpus/images/{image}.img not generated yet — run `just corpus` first")


@pytest.mark.slow
def test_detect_matches_truth_device_fields() -> None:
    _skip_if_missing("hiksim_clean")
    truth = json.loads((TRUTH_DIR / "hiksim_clean.json").read_text())
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_clean.img")) as r:
        match = registry.get("hiksim").detect(r)
    assert match is not None
    assert match.family == "hiksim"
    assert match.tier == "A"
    assert match.confidence == 1.0
    assert match.model == truth["device"]["model"]
    assert match.serial == truth["device"]["serial"]


@pytest.mark.slow
@pytest.mark.parametrize("image", ["hiksim_clean", "hiksim_clockchange", "hiksim_format"])
def test_list_recordings_matches_truth(image: str) -> None:
    _skip_if_missing(image)
    truth = json.loads((TRUTH_DIR / f"{image}.json").read_text())
    live_truth = [rec for rec in truth["recordings"] if rec["indexed"]]

    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        recs = registry.get("hiksim").list_recordings(r)

    assert len(recs) == len(live_truth)
    live_truth_by_offset = {rec["byte_ranges"][0][0]: rec for rec in live_truth}
    for rec in recs:
        t = live_truth_by_offset[rec.byte_ranges[0].offset]
        assert rec.channel == t["channel"]
        assert rec.byte_ranges[0].length == t["byte_ranges"][0][1]
        assert not rec.deleted
        assert rec.source == "index"


@pytest.mark.slow
@pytest.mark.parametrize("image", ["hiksim_clean", "hiksim_clockchange", "hiksim_format"])
def test_iter_frames_exactly_matches_truth_live_frames(image: str) -> None:
    _skip_if_missing(image)
    truth_frames = pq.read_table(TRUTH_DIR / f"{image}.frames.parquet").to_pylist()
    live_truth = [f for f in truth_frames if not f["deleted"]]
    truth_by_offset = {f["payload_offset"]: f for f in live_truth}

    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        parser = registry.get("hiksim")
        recs = parser.list_recordings(r)
        parsed = [f for rec in recs for f in parser.iter_frames(r, rec)]

    assert len(parsed) == len(live_truth)
    for f in parsed:
        t = truth_by_offset[f.payload_offset]
        assert f.payload_len == t["payload_len"]
        assert f.header_offset == t["header_offset"]
        assert f.frame_type == t["frame_type"]
        assert f.channel == t["channel"]
        assert f.ts_header_us == t["ts_device_us"]
        assert f.codec == "h264"
        assert f.source == "index"
        assert not f.deleted


@pytest.mark.slow
def test_unindexed_ranges_cover_the_orphaned_deleted_blocks() -> None:
    """After a format, gen1's second round of recordings (4 of the 8
    original recordings) is entirely absent from the live HIKBTREE, and
    gen1's first round is only partially overwritten by gen2 reusing the
    same physical blocks — either way, every deleted-and-not-fully-
    overwritten byte must fall inside ``unindexed_ranges`` for the carver
    to find (the physically-overwritten prefix legitimately does not)."""
    _skip_if_missing("hiksim_format")
    truth_frames = pq.read_table(TRUTH_DIR / "hiksim_format.frames.parquet").to_pylist()
    recoverable = [f for f in truth_frames if f["deleted"] and not f["overwritten"]]
    assert recoverable  # sanity: the fixture really does have recoverable deletions

    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_format.img")) as r:
        ranges = registry.get("hiksim").unindexed_ranges(r)

    for f in recoverable:
        start, end = f["payload_offset"], f["payload_offset"] + f["payload_len"]
        assert any(rng.offset <= start and end <= rng.offset + rng.length for rng in ranges), (
            f"recoverable frame at 0x{start:x} not covered by any unindexed range"
        )
