"""Read-only evidence image access: raw (dd) and E01 (via ``pyewf``, optional).

CLAUDE.md rule 1: evidence is read-only. Every path here opens with
``os.O_RDONLY`` (raw) or ``pyewf``'s handle (E01, itself read-only by
construction); nothing in this module ever writes, truncates, or ``mmap``s
with write access to an evidence file. CLAUDE.md rule 2: this is the *only*
place that opens evidence files — everything else asks an ``EvidenceReader``
for bytes.
"""

from __future__ import annotations

import mmap
import os
from collections.abc import Iterator
from types import TracebackType
from typing import Literal, Protocol

from pramaan_core.hashing import DEFAULT_CHUNK, ProgressCallback, hash_stream

#: E01/EWF container magic (docs/01-FORENSIC-CORE.md §4.1).
E01_MAGIC = b"EVF\x09\x0d\x0a\xff\x00"


class UnsupportedFormat(Exception):
    """Raised when an image format can't be read in this environment.

    The only current case: an E01 image when ``pyewf`` is not installed.
    Raw images are never affected.
    """


class _E01Handle(Protocol):
    def open(self, filenames: list[str]) -> None: ...
    def get_media_size(self) -> int: ...
    def seek(self, offset: int) -> None: ...
    def read(self, length: int) -> bytes: ...
    def close(self) -> None: ...


class EvidenceReader:
    """Read-only reader over a raw (dd) or E01 evidence image.

    Construct with :meth:`open`, not directly. Use as a context manager or
    call :meth:`close` explicitly when done.
    """

    def __init__(
        self,
        path: str,
        fmt: Literal["raw", "e01"],
        size: int,
        raw_fd: int | None = None,
        e01_handle: _E01Handle | None = None,
    ) -> None:
        self.path = path
        self.format = fmt
        self.size = size
        self._raw_fd = raw_fd
        self._e01_handle = e01_handle

    @classmethod
    def open(cls, path: str) -> EvidenceReader:
        """Detect raw vs. E01 by magic and open accordingly."""
        with open(path, "rb") as probe:
            head = probe.read(len(E01_MAGIC))
        if head == E01_MAGIC:
            return cls._open_e01(path)
        return cls._open_raw(path)

    @classmethod
    def _open_raw(cls, path: str) -> EvidenceReader:
        fd = os.open(path, os.O_RDONLY)
        size = os.fstat(fd).st_size
        return cls(path, "raw", size, raw_fd=fd)

    @classmethod
    def _open_e01(cls, path: str) -> EvidenceReader:
        try:
            import pyewf
        except ImportError as exc:
            raise UnsupportedFormat(
                f"E01 image {path!r} requires pyewf, which is not installed in "
                "this environment; raw images are unaffected "
                "(docs/01-FORENSIC-CORE.md §6)."
            ) from exc
        filenames = pyewf.glob(path)
        handle: _E01Handle = pyewf.handle()
        handle.open(filenames)
        size = handle.get_media_size()
        return cls(path, "e01", size, e01_handle=handle)

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes starting at absolute ``offset``."""
        if self._raw_fd is not None:
            return os.pread(self._raw_fd, length, offset)
        assert self._e01_handle is not None
        self._e01_handle.seek(offset)
        return self._e01_handle.read(length)

    def iter_chunks(self, chunk: int = DEFAULT_CHUNK) -> Iterator[bytes]:
        """Yield the image contents from the start in ``chunk``-sized pieces."""
        offset = 0
        while offset < self.size:
            n = min(chunk, self.size - offset)
            data = self.read(offset, n)
            if not data:
                break
            offset += len(data)
            yield data

    def mmap_readonly(self) -> mmap.mmap:
        """Memory-map the image read-only (``ACCESS_READ``). Raw images only."""
        if self._raw_fd is None:
            raise UnsupportedFormat("mmap_readonly is only available for raw images")
        return mmap.mmap(self._raw_fd, 0, access=mmap.ACCESS_READ)

    def close(self) -> None:
        if self._raw_fd is not None:
            os.close(self._raw_fd)
        elif self._e01_handle is not None:
            self._e01_handle.close()

    def __enter__(self) -> EvidenceReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def hash_image(
    reader: EvidenceReader, progress: ProgressCallback | None = None
) -> tuple[str, str]:
    """Stream-hash ``reader``'s full contents in one pass.

    Returns ``(sha256_hex, md5_hex)``; ``progress(bytes_done, total)`` is
    called after every chunk when given.
    """
    return hash_stream(reader.iter_chunks(), total=reader.size, progress=progress)
