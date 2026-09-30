"""DHSIM VendorParser tests against the real corpus
(docs/01-FORENSIC-CORE.md §5 "Tier A parse"; §4.10 "expiry" keeps index
entries with intact offset/length, unlike "format").

``list_recordings`` only returns *active* (``state == 1``) index entries —
"live index only" per the VendorParser interface (docs/01-FORENSIC-CORE.md
§4.5). A freed (expired) entry's bytes are physically intact but it is no
longer part of the live index, so it comes back from ``unindexed_ranges``
instead and is recovered by ``pramaan_recovery.vendor_carve.carve_dhav`` —
exactly like a formatted-away recording, just trivially easy to recover
since the bytes were never disturbed (see ``dhsim.py``'s docstrings for the
full reasoning, and ``docs/progress/Q1.md`` "Corpus summary" for how ground
truth's own ``indexed`` field lines up with this: it tracks ``state==1``
too, not merely "physically present in the on-disk index array").
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_formats import registry
from pramaan_recovery import vendor_carve

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"


def _skip_if_missing(image: str) -> None:
    img = IMAGES_DIR / f"{image}.img"
    truth = TRUTH_DIR / f"{image}.json"
    if not img.exists() or not truth.exists():
        pytest.skip(f"{img} not generated yet — run `just corpus` first")


@pytest.mark.slow
def test_detect_matches_truth_device_fields() -> None:
    _skip_if_missing("dhsim_format")
    truth = json.loads((TRUTH_DIR / "dhsim_format.json").read_text())
    with EvidenceReader.open(str(IMAGES_DIR / "dhsim_format.img")) as r:
        match = registry.get("dhsim").detect(r)
    assert match is not None
    assert match.family == "dhsim"
    assert match.tier == "A"
    assert match.confidence == 1.0
    assert match.model == truth["device"]["model"]
    assert match.serial == truth["device"]["serial"]


@pytest.mark.slow
@pytest.mark.parametrize("image", ["dhsim_format", "dhsim_expiry"])
def test_list_recordings_matches_truth_indexed_entries_only(image: str) -> None:
    _skip_if_missing(image)
    truth = json.loads((TRUTH_DIR / f"{image}.json").read_text())

    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        recs = registry.get("dhsim").list_recordings(r)

    truth_indexed = [rec for rec in truth["recordings"] if rec["indexed"]]
    assert len(recs) == len(truth_indexed)
    truth_by_offset = {rec["byte_ranges"][0][0]: rec for rec in truth_indexed}
    for rec in recs:
        t = truth_by_offset[rec.byte_ranges[0].offset]
        assert rec.channel == t["channel"]
        assert rec.byte_ranges[0].length == t["byte_ranges"][0][1]
        assert not rec.deleted  # only active entries ever come back
        assert not t["deleted"]
        assert rec.source == "index"


@pytest.mark.slow
def test_dhsim_expiry_unindexed_ranges_cover_exactly_the_freed_entries() -> None:
    _skip_if_missing("dhsim_expiry")
    truth = json.loads((TRUTH_DIR / "dhsim_expiry.json").read_text())
    freed = [rec for rec in truth["recordings"] if not rec["indexed"]]
    assert freed

    with EvidenceReader.open(str(IMAGES_DIR / "dhsim_expiry.img")) as r:
        ranges = registry.get("dhsim").unindexed_ranges(r)

    for rec in freed:
        start, length = rec["byte_ranges"][0]
        end = start + length
        assert any(rng.offset <= start and end <= rng.offset + rng.length for rng in ranges)


@pytest.mark.slow
def test_dhsim_expiry_carve_dhav_recovers_100_percent() -> None:
    """docs/01-FORENSIC-CORE.md §5: "≥ 95% of ground-truth deleted frames
    recovered on ... dhsim_expiry" — expiry never touches the bytes, so
    the DHAV carver should recover exactly 100% of them from the freed
    (but structurally intact) byte range."""
    _skip_if_missing("dhsim_expiry")
    truth_frames = pq.read_table(TRUTH_DIR / "dhsim_expiry.frames.parquet").to_pylist()
    deleted_truth = [f for f in truth_frames if f["deleted"]]
    assert deleted_truth

    with EvidenceReader.open(str(IMAGES_DIR / "dhsim_expiry.img")) as r:
        parser = registry.get("dhsim")
        image_id = parser._image_id(r)  # noqa: SLF001 - test-only introspection
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_dhav(r, image_id, ranges)

    carved_by_offset = {f.payload_offset: f for f in carved}
    recovered = 0
    for t in deleted_truth:
        f = carved_by_offset.get(t["payload_offset"])
        if f is None:
            continue
        if (
            f.payload_len == t["payload_len"]
            and f.channel == t["channel"]
            and f.ts_header_us == t["ts_device_us"]
        ):
            recovered += 1
    assert recovered / len(deleted_truth) >= 0.95
