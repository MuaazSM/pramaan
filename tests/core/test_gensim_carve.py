"""Generic carver against the real GENSIM corpus image
(docs/01-FORENSIC-CORE.md §5 "Carver: GENSIM: >= 95% frames recovered,
channels separated correctly"; §4.7 step 4, SPS-based channel clustering).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import ByteRange
from pramaan_recovery import carve

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"

RECOVERY_FLOOR = 0.95


def _skip_if_missing() -> None:
    if not (IMAGES_DIR / "gensim_carve.img").exists():
        pytest.skip("corpus/images/gensim_carve.img not generated yet — run `just corpus` first")


@pytest.mark.slow
def test_gensim_carve_recovers_at_least_95_percent_of_frames() -> None:
    _skip_if_missing()
    truth = pq.read_table(TRUTH_DIR / "gensim_carve.frames.parquet").to_pylist()
    assert truth

    with EvidenceReader.open(str(IMAGES_DIR / "gensim_carve.img")) as r:
        frames = carve.carve_annexb(r, "img_test", [ByteRange(offset=0, length=r.size)])

    frames_by_offset = {f.payload_offset: f for f in frames}
    recovered = 0
    for t in truth:
        f = frames_by_offset.get(t["payload_offset"])
        if f is not None and f.payload_len == t["payload_len"]:
            recovered += 1
    fraction = recovered / len(truth)
    assert fraction >= RECOVERY_FLOOR, f"only {fraction:.1%} of GENSIM frames recovered"


@pytest.mark.slow
def test_gensim_carve_separates_channels_correctly() -> None:
    """Every truth channel must map to exactly one carved channel id (SPS
    resolution-based clustering, docs/01-FORENSIC-CORE.md §4.7 step 4) —
    GENSIM's three channels use distinct resolutions specifically to make
    this possible."""
    _skip_if_missing()
    truth = pq.read_table(TRUTH_DIR / "gensim_carve.frames.parquet").to_pylist()

    with EvidenceReader.open(str(IMAGES_DIR / "gensim_carve.img")) as r:
        frames = carve.carve_annexb(r, "img_test", [ByteRange(offset=0, length=r.size)])

    frames_by_offset = {f.payload_offset: f for f in frames}
    mapping: dict[int, set[int | None]] = {}
    for t in truth:
        f = frames_by_offset.get(t["payload_offset"])
        if f is None:
            continue
        mapping.setdefault(t["channel"], set()).add(f.channel)
    assert len(mapping) >= 2  # sanity: the fixture really has multiple channels
    for truth_channel, carved_channels in mapping.items():
        assert len(carved_channels) == 1, (
            f"truth channel {truth_channel} scattered across carved channels "
            f"{carved_channels}"
        )
