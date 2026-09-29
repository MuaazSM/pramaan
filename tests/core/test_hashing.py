"""Streaming dual hashing vs. hashlib ground truth."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pramaan_core.hashing import hash_file, hash_stream


def test_hash_file_matches_hashlib(tmp_path: Path) -> None:
    data = os.urandom(5 * 1024 * 1024 + 137)  # not a clean multiple of chunk size
    path = tmp_path / "sample.bin"
    path.write_bytes(data)

    sha256, md5 = hash_file(str(path), chunk_size=1024 * 1024)

    assert sha256 == hashlib.sha256(data).hexdigest()
    assert md5 == hashlib.md5(data).hexdigest()


def test_hash_stream_progress_callback() -> None:
    chunks = [b"a" * 10, b"b" * 5]
    seen: list[tuple[int, int]] = []

    def _progress(done: int, total: int) -> None:
        seen.append((done, total))

    sha256, md5 = hash_stream(iter(chunks), total=15, progress=_progress)

    assert seen == [(10, 15), (15, 15)]
    assert sha256 == hashlib.sha256(b"a" * 10 + b"b" * 5).hexdigest()
    assert md5 == hashlib.md5(b"a" * 10 + b"b" * 5).hexdigest()


def test_hash_stream_without_total_uses_done_as_total() -> None:
    seen: list[tuple[int, int]] = []
    hash_stream(iter([b"xy"]), progress=lambda done, total: seen.append((done, total)))
    assert seen == [(2, 2)]
