"""Cheap, always-fast sanity checks against whatever `corpus/` already
contains on disk. `corpus/images/` and the frames Parquet files are
gitignored (regenerable), so on a clean clone this whole module skips —
`just corpus` (docs/05-INFRA-QA.md §4) is what actually populates them, and
CI runs `just check-qa` before `just corpus` per `.github/workflows/ci.yml`.
Once images exist (locally, or later in the same CI run), this validates
the Q1 acceptance criteria directly against them: manifest hashes match the
files on disk, every image is within the "small" profile's 128 MiB cap, and
every image's ground truth is self-consistent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pramaan_synthdvr.truth import check_self_consistency

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"
MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"

SMALL_PROFILE_LIMIT_BYTES = 128 * 1024 * 1024

OWNED_FAMILIES = {"hiksim", "dhsim", "gensim"}  # Q1; hwsim/xsim are Q2


def _manifest_images() -> list[dict[str, object]]:
    if not MANIFEST_PATH.exists():
        return []
    doc = json.loads(MANIFEST_PATH.read_text())
    images = doc.get("images") or []
    assert isinstance(images, list)
    return [e for e in images if e.get("family") in OWNED_FAMILIES]


@pytest.mark.parametrize("entry", _manifest_images(), ids=lambda e: str(e["name"]))
def test_manifest_entry_matches_disk(entry: dict[str, object]) -> None:
    img_path = REPO_ROOT / str(entry["path"])
    if not img_path.exists():
        pytest.skip(f"{img_path} not generated yet — run `just corpus` first")
    data = img_path.read_bytes()
    assert len(data) <= SMALL_PROFILE_LIMIT_BYTES, (
        f"{entry['name']}: {len(data)} bytes exceeds the small-profile 128 MiB cap"
    )
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert len(data) == entry["size_bytes"]


@pytest.mark.parametrize("entry", _manifest_images(), ids=lambda e: str(e["name"]))
def test_ground_truth_self_consistent(entry: dict[str, object]) -> None:
    img_path = REPO_ROOT / str(entry["path"])
    if not img_path.exists():
        pytest.skip(f"{img_path} not generated yet — run `just corpus` first")
    errs = check_self_consistency(img_path, TRUTH_DIR, str(entry["name"]))
    assert errs == [], "\n".join(errs)


def test_no_xsim_leak_placeholder() -> None:
    """XSIM itself is Q2's job (docs/01-FORENSIC-CORE.md §4.6 rules for
    CORE agents), so there is nothing to leak from Q1's writers. This is a
    trivial placeholder so the real leak test
    (`tests/validation/test_no_xsim_leak.py`, owned by whichever task adds
    XSIM) has an established pattern to follow, and so this module doesn't
    silently collect zero tests if `corpus/manifest.json` is empty."""
    assert "xsim" not in OWNED_FAMILIES
