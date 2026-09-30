"""Whole-pipeline determinism for C2's outputs (docs/01-FORENSIC-CORE.md §5
"Determinism: running the pipeline twice yields identical Parquet and DB
content hashes")."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_core.frames import index_path, write_frames
from pramaan_formats import registry

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"


def _skip_if_missing(image: str) -> None:
    if not (IMAGES_DIR / f"{image}.img").exists():
        pytest.skip(f"corpus/images/{image}.img not generated yet — run `just corpus` first")


@pytest.mark.slow
@pytest.mark.parametrize("image,family", [("hiksim_clean", "hiksim"), ("dhsim_format", "dhsim")])
def test_frame_index_parquet_is_byte_identical_across_two_runs(
    image: str, family: str, tmp_path: Path
) -> None:
    _skip_if_missing(image)
    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        parser = registry.get(family)
        recs = parser.list_recordings(r)
        frames = [f for rec in recs for f in parser.iter_frames(r, rec)]
        image_id = frames[0].image_id

        case_a, case_b = tmp_path / "case_a", tmp_path / "case_b"
        write_frames(case_a, image_id, frames)
        write_frames(case_b, image_id, frames)

    bytes_a = index_path(case_a, image_id).read_bytes()
    bytes_b = index_path(case_b, image_id).read_bytes()
    assert hashlib.sha256(bytes_a).hexdigest() == hashlib.sha256(bytes_b).hexdigest()


@pytest.mark.slow
def test_list_recordings_and_iter_frames_are_deterministic(tmp_path: Path) -> None:
    _skip_if_missing("hiksim_format")
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_format.img")) as r:
        parser_a = registry.get("hiksim")
        parser_b = registry.get("hiksim")
        recs_a = parser_a.list_recordings(r)
        recs_b = parser_b.list_recordings(r)
        assert recs_a == recs_b

        frames_a = [f for rec in recs_a for f in parser_a.iter_frames(r, rec)]
        frames_b = [f for rec in recs_b for f in parser_b.iter_frames(r, rec)]
        assert frames_a == frames_b
