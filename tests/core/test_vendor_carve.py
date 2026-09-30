"""DHAV and HIKSIM-PS vendor carvers against the real corpus
(docs/01-FORENSIC-CORE.md §4.7 step 7; §5 "Deleted recovery: ≥ 95% of
ground-truth deleted frames recovered on each Tier A deletion scenario").

The denominator is "recoverable" deleted frames — deleted *and not
physically overwritten* — matching how the corpus itself is built
(docs/progress/Q1.md "Decisions": ``hiksim_format``/``dhsim_format``
deliberately overwrite a prefix of the reused region, which *no* carver
can recover; ``overwritten`` in ground truth marks exactly that subset).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_formats import registry
from pramaan_recovery import vendor_carve

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"

RECOVERY_FLOOR = 0.95


def _skip_if_missing(image: str) -> None:
    if not (IMAGES_DIR / f"{image}.img").exists():
        pytest.skip(f"corpus/images/{image}.img not generated yet — run `just corpus` first")


def _recoverable_truth(image: str) -> list[dict[str, object]]:
    frames = pq.read_table(TRUTH_DIR / f"{image}.frames.parquet").to_pylist()
    return [f for f in frames if f["deleted"] and not f["overwritten"]]


@pytest.mark.slow
def test_carve_hiksim_ps_recovers_at_least_95_percent_of_recoverable_deleted_frames() -> None:
    _skip_if_missing("hiksim_format")
    recoverable = _recoverable_truth("hiksim_format")
    assert recoverable  # sanity: the fixture really does model this

    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_format.img")) as r:
        parser = registry.get("hiksim")
        image_id = parser._image_id(r)  # noqa: SLF001 - test-only introspection
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_hiksim_ps(r, image_id, ranges)

    carved_by_offset = {f.payload_offset: f for f in carved}
    recovered = 0
    for t in recoverable:
        f = carved_by_offset.get(t["payload_offset"])
        if f is None:
            continue
        if (
            f.payload_len == t["payload_len"]
            and f.channel == t["channel"]
            and f.ts_header_us == t["ts_device_us"]
            and f.frame_type == t["frame_type"]
            and f.source == "carved"
            and f.deleted
        ):
            recovered += 1
    fraction = recovered / len(recoverable)
    assert fraction >= RECOVERY_FLOOR, f"only {fraction:.1%} of recoverable frames recovered"


@pytest.mark.slow
def test_carve_dhav_recovers_at_least_95_percent_of_recoverable_deleted_frames() -> None:
    _skip_if_missing("dhsim_format")
    recoverable = _recoverable_truth("dhsim_format")
    assert recoverable

    with EvidenceReader.open(str(IMAGES_DIR / "dhsim_format.img")) as r:
        parser = registry.get("dhsim")
        image_id = parser._image_id(r)  # noqa: SLF001 - test-only introspection
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_dhav(r, image_id, ranges)

    carved_by_offset = {f.payload_offset: f for f in carved}
    recovered = 0
    for t in recoverable:
        f = carved_by_offset.get(t["payload_offset"])
        if f is None:
            continue
        if (
            f.payload_len == t["payload_len"]
            and f.channel == t["channel"]
            and f.ts_header_us == t["ts_device_us"]
            and f.frame_type == t["frame_type"]
            and f.source == "carved"
            and f.deleted
        ):
            recovered += 1
    fraction = recovered / len(recoverable)
    assert fraction >= RECOVERY_FLOOR, f"only {fraction:.1%} of recoverable frames recovered"


@pytest.mark.slow
def test_carve_hwsim_recovers_at_least_95_percent_of_recoverable_deleted_frames() -> None:
    """hwsim_format's fully-overwritten round (100% loss, no trace at all)
    is intentionally excluded from the "recoverable" denominator, same as
    every other format's deliberately-unrecoverable prefix — see
    docs/progress/C3.md "Decisions" for why HWSIM's format scenario has no
    partial-prefix overwrite (it's all-or-nothing per round)."""
    _skip_if_missing("hwsim_format")
    recoverable = _recoverable_truth("hwsim_format")
    assert recoverable

    with EvidenceReader.open(str(IMAGES_DIR / "hwsim_format.img")) as r:
        parser = registry.get("hwsim")
        image_id = parser._image_id(r)  # noqa: SLF001
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_hwsim(r, image_id, ranges)

    carved_by_offset = {f.payload_offset: f for f in carved}
    recovered = 0
    for t in recoverable:
        f = carved_by_offset.get(t["payload_offset"])
        if f is None:
            continue
        if (
            f.payload_len == t["payload_len"]
            and f.channel == t["channel"]
            and f.ts_header_us == t["ts_device_us"]
            and f.frame_type == t["frame_type"]
            and f.source == "carved"
            and f.deleted
        ):
            recovered += 1
    fraction = recovered / len(recoverable)
    assert fraction >= RECOVERY_FLOOR, f"only {fraction:.1%} of recoverable frames recovered"


@pytest.mark.slow
def test_carve_hwsim_finds_nothing_when_nothing_is_recoverable() -> None:
    """hwsim_overwrite's wiped round leaves literally zero surviving bytes
    (its old slot is 100% occupied by the newer round that overwrote it) —
    the carver must not fabricate frames there."""
    _skip_if_missing("hwsim_overwrite")
    recoverable = _recoverable_truth("hwsim_overwrite")
    assert recoverable == []  # sanity: this scenario really is unrecoverable

    with EvidenceReader.open(str(IMAGES_DIR / "hwsim_overwrite.img")) as r:
        parser = registry.get("hwsim")
        image_id = parser._image_id(r)  # noqa: SLF001
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_hwsim(r, image_id, ranges)
    assert carved == []


@pytest.mark.slow
def test_carve_hwsim_never_reports_frames_outside_the_given_ranges() -> None:
    _skip_if_missing("hwsim_format")
    with EvidenceReader.open(str(IMAGES_DIR / "hwsim_format.img")) as r:
        parser = registry.get("hwsim")
        image_id = parser._image_id(r)  # noqa: SLF001
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_hwsim(r, image_id, ranges)
    for f in carved:
        assert any(
            rng.offset <= f.payload_offset < rng.offset + rng.length for rng in ranges
        ), f"frame at {f.payload_offset} outside every requested range"


@pytest.mark.slow
def test_carve_hiksim_ps_never_reports_frames_outside_the_given_ranges() -> None:
    """Sanity/regression guard: a false-positive candidate offset (a
    coincidental "00 00 01 BA" byte sequence inside compressed data) must
    never survive structural validation and leak a bogus frame."""
    _skip_if_missing("hiksim_format")
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_format.img")) as r:
        parser = registry.get("hiksim")
        image_id = parser._image_id(r)  # noqa: SLF001
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_hiksim_ps(r, image_id, ranges)
    for f in carved:
        assert any(
            rng.offset <= f.payload_offset < rng.offset + rng.length for rng in ranges
        ), f"frame at {f.payload_offset} outside every requested range"
