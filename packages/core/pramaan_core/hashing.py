"""Streaming dual hashing (SHA-256 + MD5), one pass over the bytes.

Used by acquisition/registration (``pramaan_core.acquire``) and by
``EvidenceReader``-based hashing (``pramaan_core.evidence.hash_image``) so
every workstream computes hashes the same way.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable

#: Chunk size used throughout core I/O (docs/01-FORENSIC-CORE.md §4.1/4.2).
DEFAULT_CHUNK = 8 * 1024 * 1024  # 8 MiB

ProgressCallback = Callable[[int, int], None]


def hash_stream(
    chunks: Iterable[bytes],
    total: int | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[str, str]:
    """Hash ``chunks`` in one streaming pass, returning ``(sha256_hex, md5_hex)``.

    Calls ``progress(bytes_done, total)`` after every chunk when given; if
    ``total`` is ``None``, ``bytes_done`` is passed as both arguments.
    """
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    done = 0
    for chunk in chunks:
        sha256.update(chunk)
        md5.update(chunk)
        done += len(chunk)
        if progress is not None:
            progress(done, total if total is not None else done)
    return sha256.hexdigest(), md5.hexdigest()


def hash_file(
    path: str,
    chunk_size: int = DEFAULT_CHUNK,
    progress: ProgressCallback | None = None,
) -> tuple[str, str]:
    """Hash the file at ``path``, opened read-only (``os.O_RDONLY``).

    Streams in ``chunk_size`` chunks; never mutates the file (CLAUDE.md
    rule 1).
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        total = os.fstat(fd).st_size

        def _chunks() -> Iterable[bytes]:
            while True:
                buf = os.read(fd, chunk_size)
                if not buf:
                    break
                yield buf

        return hash_stream(_chunks(), total=total, progress=progress)
    finally:
        os.close(fd)
