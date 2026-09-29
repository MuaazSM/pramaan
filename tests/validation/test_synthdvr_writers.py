"""Full-writer acceptance tests for Q1 (docs/05-INFRA-QA.md §4, Q1 task
brief "Acceptance criteria"): determinism (same config -> same SHA-256),
ground-truth self-consistency, and the small-profile size cap. These build
real images (via ffmpeg) so they're marked `slow` and excluded from the
default `just check-qa` run; `just corpus` exercises the same code paths
against the real corpus and is what the Q1 "Verify" step actually gates on.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pramaan_synthdvr.truth import check_self_consistency
from pramaan_synthdvr.writers import dhsim, gensim, hiksim

SMALL_PROFILE_LIMIT_BYTES = 128 * 1024 * 1024

pytestmark = pytest.mark.slow


def _build_and_check(build_fn, name: str, tmp_path: Path) -> Path:
    images_dir = tmp_path / "images"
    truth_dir = tmp_path / "truth"
    path = build_fn(images_dir, truth_dir)
    errs = check_self_consistency(path, truth_dir, name)
    assert errs == [], f"{name}: ground-truth self-consistency failed:\n" + "\n".join(errs)
    assert path.stat().st_size <= SMALL_PROFILE_LIMIT_BYTES
    return path


@pytest.mark.parametrize(
    ("name", "build_fn"),
    [
        ("hiksim_clean", lambda d, t: hiksim.build_image("hiksim_clean", d, t, scenario="clean")),
        (
            "hiksim_format",
            lambda d, t: hiksim.build_image("hiksim_format", d, t, scenario="format"),
        ),
        (
            "hiksim_clockchange",
            lambda d, t: hiksim.build_image("hiksim_clockchange", d, t, scenario="clockchange"),
        ),
        ("dhsim_format", lambda d, t: dhsim.build_image("dhsim_format", d, t, scenario="format")),
        ("dhsim_expiry", lambda d, t: dhsim.build_image("dhsim_expiry", d, t, scenario="expiry")),
        ("gensim_carve", lambda d, t: gensim.build_image("gensim_carve", d, t)),
    ],
)
def test_self_consistency_and_size(name, build_fn, tmp_path: Path) -> None:
    _build_and_check(build_fn, name, tmp_path)


@pytest.mark.parametrize(
    ("name", "build_fn"),
    [
        (
            "hiksim_format",
            lambda d, t: hiksim.build_image("hiksim_format", d, t, scenario="format"),
        ),
        ("dhsim_expiry", lambda d, t: dhsim.build_image("dhsim_expiry", d, t, scenario="expiry")),
        ("gensim_carve", lambda d, t: gensim.build_image("gensim_carve", d, t)),
    ],
)
def test_determinism_same_config_same_hash(name, build_fn, tmp_path: Path) -> None:
    """Same config, built twice into separate directories, must produce a
    byte-identical image (CLAUDE.md rule 5 / docs/05-INFRA-QA.md §4.2)."""
    path_a = build_fn(tmp_path / "run_a" / "images", tmp_path / "run_a" / "truth")
    path_b = build_fn(tmp_path / "run_b" / "images", tmp_path / "run_b" / "truth")
    sha_a = hashlib.sha256(path_a.read_bytes()).hexdigest()
    sha_b = hashlib.sha256(path_b.read_bytes()).hexdigest()
    assert sha_a == sha_b
