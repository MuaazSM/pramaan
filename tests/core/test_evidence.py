"""EvidenceReader: raw reads, read-only guarantee, E01 handling."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from pramaan_core.evidence import E01_MAGIC, EvidenceReader, UnsupportedFormat, hash_image


def _make_image(tmp_path: Path, size: int = 1024 * 1024 + 17) -> Path:
    path = tmp_path / "image.raw"
    path.write_bytes(os.urandom(size))
    return path


def test_open_detects_raw(tmp_path: Path) -> None:
    path = _make_image(tmp_path)
    reader = EvidenceReader.open(str(path))
    try:
        assert reader.format == "raw"
        assert reader.size == path.stat().st_size
    finally:
        reader.close()


def test_read_and_iter_chunks_match_full_file(tmp_path: Path) -> None:
    path = _make_image(tmp_path, size=3 * 1024 * 1024 + 5)
    data = path.read_bytes()
    reader = EvidenceReader.open(str(path))
    try:
        assert reader.read(10, 20) == data[10:30]
        assembled = b"".join(reader.iter_chunks(chunk=1024 * 1024))
        assert assembled == data
    finally:
        reader.close()


def test_context_manager_closes(tmp_path: Path) -> None:
    path = _make_image(tmp_path, size=64)
    with EvidenceReader.open(str(path)) as reader:
        assert reader.read(0, 64) == path.read_bytes()


def test_read_only_guarantee(tmp_path: Path) -> None:
    """Image mtime and hash are unchanged after a full read/hash/mmap pass
    (CLAUDE.md rule 1; docs/01-FORENSIC-CORE.md §4.1)."""
    path = _make_image(tmp_path)
    before_mtime = path.stat().st_mtime_ns
    before_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    reader = EvidenceReader.open(str(path))
    try:
        sha256, _md5 = hash_image(reader)
        for _ in reader.iter_chunks():
            pass
        mm = reader.mmap_readonly()
        try:
            _ = mm[:16]
        finally:
            mm.close()
    finally:
        reader.close()

    after_mtime = path.stat().st_mtime_ns
    after_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    assert before_mtime == after_mtime
    assert before_sha256 == after_sha256 == sha256


def test_mmap_readonly_rejects_write(tmp_path: Path) -> None:
    import mmap as mmap_module

    path = _make_image(tmp_path, size=64)
    reader = EvidenceReader.open(str(path))
    try:
        mm = reader.mmap_readonly()
        try:
            with pytest.raises(TypeError):
                mm[0:1] = b"\x00"
        finally:
            mm.close()
    finally:
        reader.close()
    assert mmap_module  # imported only to document ACCESS_READ behaviour above


def test_e01_without_pyewf_raises(tmp_path: Path) -> None:
    try:
        import pyewf  # noqa: F401

        pytest.skip("pyewf is installed; UnsupportedFormat fallback not exercised here")
    except ImportError:
        pass

    path = tmp_path / "image.E01"
    path.write_bytes(E01_MAGIC + b"\x00" * 64)
    with pytest.raises(UnsupportedFormat):
        EvidenceReader.open(str(path))
