"""acquire() and register_existing() tests (raw path — no ewfacquire dependency)."""

from __future__ import annotations

import os
from pathlib import Path

from pramaan_core.acquire import acquire, register_existing


def test_register_existing_hashes_and_leaves_file_untouched(tmp_path: Path) -> None:
    path = tmp_path / "src.raw"
    path.write_bytes(os.urandom(4096))
    before_mtime = path.stat().st_mtime_ns

    image = register_existing(path)

    assert image.path == str(path)
    assert image.format == "raw"
    assert image.verified is True
    assert image.id == f"img_{image.sha256[:16]}"
    assert path.stat().st_mtime_ns == before_mtime


def test_register_existing_is_deterministic_on_content(tmp_path: Path) -> None:
    data = os.urandom(4096)
    p1 = tmp_path / "a.raw"
    p2 = tmp_path / "b.raw"
    p1.write_bytes(data)
    p2.write_bytes(data)

    img1 = register_existing(p1)
    img2 = register_existing(p2)

    assert img1.sha256 == img2.sha256
    assert img1.md5 == img2.md5
    assert img1.id == img2.id


def test_acquire_raw_copy_verifies_and_records_provenance(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src = src_dir / "evidence.raw"
    src.write_bytes(os.urandom(2 * 1024 * 1024 + 3))
    before_mtime = src.stat().st_mtime_ns
    before_hash = register_existing(src).sha256

    dest_dir = tmp_path / "dest"
    image = acquire(src, dest_dir, fmt="raw")

    assert image.verified is True
    assert image.sha256 == before_hash
    assert Path(image.path).exists()
    assert Path(image.path).parent == dest_dir
    assert src.stat().st_mtime_ns == before_mtime  # source untouched

    sidecar = Path(str(image.path) + ".provenance.json")
    assert sidecar.exists()
    assert b'"step":"acquire.acquire"' in sidecar.read_bytes()
    assert before_hash.encode() in sidecar.read_bytes()
