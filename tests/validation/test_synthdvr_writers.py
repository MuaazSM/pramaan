"""Full-writer acceptance tests (docs/05-INFRA-QA.md §4, Q1/Q2 task briefs
"Acceptance criteria"): determinism (same config -> same SHA-256),
ground-truth self-consistency, the small-profile size cap, and (HWSIM only)
GPT CRC validity. These build real images (via ffmpeg) so they're marked
`slow` and excluded from the default `just check-qa` run; `just corpus`
exercises the same code paths against the real corpus and is what the
"Verify" step actually gates on.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import pytest
from pramaan_synthdvr.truth import check_self_consistency
from pramaan_synthdvr.writers import dhsim, gensim, hiksim, hwsim, xsim

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
        ("hwsim_format", lambda d, t: hwsim.build_image("hwsim_format", d, t, scenario="format")),
        (
            "hwsim_overwrite",
            lambda d, t: hwsim.build_image("hwsim_overwrite", d, t, scenario="overwrite"),
        ),
        ("xsim_unknown", lambda d, t: xsim.build_image("xsim_unknown", d, t, scenario="none")),
        ("xsim_format", lambda d, t: xsim.build_image("xsim_format", d, t, scenario="format")),
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
        ("hwsim_format", lambda d, t: hwsim.build_image("hwsim_format", d, t, scenario="format")),
        (
            "hwsim_overwrite",
            lambda d, t: hwsim.build_image("hwsim_overwrite", d, t, scenario="overwrite"),
        ),
        ("xsim_unknown", lambda d, t: xsim.build_image("xsim_unknown", d, t, scenario="none")),
        ("xsim_format", lambda d, t: xsim.build_image("xsim_format", d, t, scenario="format")),
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


@pytest.mark.parametrize(
    ("name", "build_fn"),
    [
        ("hwsim_format", lambda d, t: hwsim.build_image("hwsim_format", d, t, scenario="format")),
        (
            "hwsim_overwrite",
            lambda d, t: hwsim.build_image("hwsim_overwrite", d, t, scenario="overwrite"),
        ),
    ],
)
def test_hwsim_gpt_crcs_are_valid(name, build_fn, tmp_path: Path) -> None:
    """docs/01-FORENSIC-CORE.md §4.6 "HWSIM": "GPT disk: ... valid CRC32s".
    Independently recomputes the primary and backup GPT header CRC32 (with
    the header_crc32 field itself zeroed, per the UEFI spec) and the
    partition-entry-array CRC32, and checks them against the bytes on disk
    — this test does not import anything from `pramaan_synthdvr.writers.hwsim`
    beyond calling `build_image`, so it can't just be trivially in sync with
    a writer bug."""
    path = build_fn(tmp_path / "images", tmp_path / "truth")
    data = path.read_bytes()
    sector = 512

    def read_header(lba: int) -> dict[str, int]:
        h = data[lba * sector : lba * sector + 92]
        assert h[0:8] == b"EFI PART"
        stored_crc = struct.unpack_from("<I", h, 16)[0]
        recomputed = bytearray(h)
        struct.pack_into("<I", recomputed, 16, 0)
        header_crc = zlib.crc32(bytes(recomputed)) & 0xFFFFFFFF
        assert header_crc == stored_crc, f"LBA {lba} header CRC32 mismatch"
        part_entry_lba = struct.unpack_from("<Q", h, 72)[0]
        num_entries = struct.unpack_from("<I", h, 80)[0]
        entry_size = struct.unpack_from("<I", h, 84)[0]
        array_crc = struct.unpack_from("<I", h, 88)[0]
        array_start = part_entry_lba * sector
        array = data[array_start : array_start + num_entries * entry_size]
        array_crc_ok = zlib.crc32(array) & 0xFFFFFFFF == array_crc
        assert array_crc_ok, f"LBA {lba} partition array CRC32 mismatch"
        my_lba = struct.unpack_from("<Q", h, 24)[0]
        alt_lba = struct.unpack_from("<Q", h, 32)[0]
        return {"my_lba": my_lba, "alt_lba": alt_lba}

    primary = read_header(1)
    assert primary["my_lba"] == 1
    backup = read_header(primary["alt_lba"])
    assert backup["my_lba"] == primary["alt_lba"]
    assert backup["alt_lba"] == 1
