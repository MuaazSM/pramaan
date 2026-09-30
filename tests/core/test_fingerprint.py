"""Fingerprinter tests (docs/01-FORENSIC-CORE.md §4.4, §5
"Fingerprinting: each corpus image's top match = ground-truth family;
confidence ≥ 0.8 for Tier A").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_formats import fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"
FINGERPRINTS_PATH = REPO_ROOT / "packages" / "formats" / "fingerprints.yaml"


def test_load_fingerprints_has_all_five_families() -> None:
    specs = fingerprint.load_fingerprints(FINGERPRINTS_PATH)
    families = {s.family for s in specs}
    assert families == {"hiksim", "dhsim", "hwsim", "xsim", "gensim"}


def test_gensim_has_no_signatures_tier_c() -> None:
    specs = {s.family: s for s in fingerprint.load_fingerprints(FINGERPRINTS_PATH)}
    assert specs["gensim"].signatures == []
    assert specs["gensim"].tier == "C"


def test_xsim_signature_matches_the_one_hint_01_allows(tmp_path: Path) -> None:
    """docs/01-FORENSIC-CORE.md §4.6: "the only hint available to CORE is a
    weak fingerprint: sector 0 contains the ASCII string XVR-GENERIC-2026".
    """
    img = tmp_path / "fake_xsim.img"
    img.write_bytes(b"\x00" * 100 + b"XVR-GENERIC-2026" + b"\x00" * 400)
    with EvidenceReader.open(str(img)) as r:
        matches = fingerprint.match(r, FINGERPRINTS_PATH)
    top = matches[0]
    assert top.family == "xsim"
    assert top.tier == "B"
    assert 0.0 < top.confidence < 0.8  # a weak hint only, per §4.4


def test_matcher_prefers_no_match_over_wrong_family(tmp_path: Path) -> None:
    img = tmp_path / "random.img"
    img.write_bytes(b"\x00" * 4096)
    with EvidenceReader.open(str(img)) as r:
        matches = fingerprint.match(r, FINGERPRINTS_PATH)
    assert matches[0].confidence == 0.0


@pytest.mark.slow
@pytest.mark.parametrize(
    "image",
    ["hiksim_clean", "hiksim_format", "hiksim_clockchange", "dhsim_format", "dhsim_expiry"],
)
def test_corpus_top_match_is_ground_truth_family_with_high_confidence(image: str) -> None:
    img_path = IMAGES_DIR / f"{image}.img"
    truth_path = TRUTH_DIR / f"{image}.json"
    if not img_path.exists() or not truth_path.exists():
        pytest.skip(f"{img_path} not generated yet — run `just corpus` first")
    truth = json.loads(truth_path.read_text())
    with EvidenceReader.open(str(img_path)) as r:
        matches = fingerprint.match(r, FINGERPRINTS_PATH)
    top = matches[0]
    assert top.family == truth["family"]
    assert top.confidence >= 0.8
