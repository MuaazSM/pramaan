"""Evidence acquisition (docs/01-FORENSIC-CORE.md §4.2).

Two entry points:

- :func:`acquire` — copy a source into the case's evidence area (via
  ``ewfacquire`` for E01 when it is on ``PATH``, else a chunked read-only
  copy for raw), then re-read the *destination* and verify both hashes
  against a first pass over the source.
- :func:`register_existing` — hash-and-register an already-present file
  without copying it. This is the common path for the synthetic corpus,
  which is generated directly where it needs to live.

Both only ever read the source with ``os.O_RDONLY`` (CLAUDE.md rule 1).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pramaan_core.evidence import EvidenceReader, hash_image
from pramaan_core.hashing import DEFAULT_CHUNK, hash_file
from pramaan_core.ids import canonical_json
from pramaan_core.models import EvidenceImage, Provenance
from pramaan_core.provenance import make_provenance
from pramaan_core.timeutil import utc_now_iso


class AcquisitionVerificationError(Exception):
    """Raised when an acquired copy's hashes don't match the source's."""


def _image_id(sha256: str) -> str:
    return f"img_{sha256[:16]}"


def _copy_chunked(source: Path, dest: Path, chunk_size: int = DEFAULT_CHUNK) -> None:
    fd = os.open(str(source), os.O_RDONLY)
    try:
        with open(dest, "wb") as out:
            while True:
                buf = os.read(fd, chunk_size)
                if not buf:
                    break
                out.write(buf)
    finally:
        os.close(fd)


def _write_provenance_sidecar(dest_path: Path, provenance: Provenance) -> Path:
    sidecar = Path(str(dest_path) + ".provenance.json")
    sidecar.write_bytes(canonical_json(provenance.model_dump()))
    return sidecar


def register_existing(path: str | Path) -> EvidenceImage:
    """Hash and register an already-present image without copying it.

    Opens read-only, streams both SHA-256 and MD5 in one pass, and returns
    an :class:`~pramaan_core.models.EvidenceImage`. The file is never
    touched — the common path for the synthetic corpus, which is generated
    directly at its final location.
    """
    resolved = Path(path)
    reader = EvidenceReader.open(str(resolved))
    try:
        sha256, md5 = hash_image(reader)
        fmt = reader.format
        size_bytes = reader.size
    finally:
        reader.close()

    return EvidenceImage(
        id=_image_id(sha256),
        path=str(resolved),
        format=fmt,
        size_bytes=size_bytes,
        sha256=sha256,
        md5=md5,
        acquired_utc=utc_now_iso(),
        verified=True,
    )


def acquire(
    source: str | Path,
    dest_dir: str | Path,
    fmt: Literal["raw", "e01"] = "raw",
) -> EvidenceImage:
    """Acquire ``source`` into ``dest_dir``, verifying the copy by hash.

    For ``fmt="e01"`` with ``ewfacquire`` on ``PATH``, shells out to it.
    Otherwise (``fmt="raw"``, or ``ewfacquire`` missing — the documented
    fallback, docs/01-FORENSIC-CORE.md §6) performs a chunked read-only copy
    and reports the format actually produced.

    Hashes the source once up front, then re-reads the destination and
    compares; raises :class:`AcquisitionVerificationError` on any mismatch.
    Records a :class:`~pramaan_core.models.Provenance` next to the copy, at
    ``<dest>.provenance.json``.
    """
    source = Path(source)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    src_sha256, src_md5 = hash_file(str(source))
    requested_fmt = fmt

    ewfacquire = shutil.which("ewfacquire") if fmt == "e01" else None
    if fmt == "e01" and ewfacquire is not None:
        target = dest_dir / source.stem
        subprocess.run(
            [
                ewfacquire,
                "-q",
                "-u",
                "-t",
                str(target),
                "-f",
                "encase6",
                "-c",
                "none",
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        dest_path = target.with_suffix(".E01")
    else:
        # Raw fallback: either fmt="raw" was requested, or E01 was requested
        # but ewfacquire isn't installed (docs/01-FORENSIC-CORE.md §6).
        dest_path = dest_dir / f"{source.stem}.raw"
        _copy_chunked(source, dest_path)
        fmt = "raw"

    dest_reader = EvidenceReader.open(str(dest_path))
    try:
        dest_sha256, dest_md5 = hash_image(dest_reader)
        size_bytes = dest_reader.size
        actual_fmt = dest_reader.format
    finally:
        dest_reader.close()

    verified = dest_sha256 == src_sha256 and dest_md5 == src_md5
    if not verified:
        raise AcquisitionVerificationError(
            f"acquired copy at {dest_path} does not hash-match source {source} "
            f"(source sha256={src_sha256}, dest sha256={dest_sha256})"
        )

    provenance = make_provenance(
        step="acquire.acquire",
        params={"source": str(source), "requested_fmt": requested_fmt, "fmt": fmt},
        parent_sha256=src_sha256,
    )
    _write_provenance_sidecar(dest_path, provenance)

    return EvidenceImage(
        id=_image_id(dest_sha256),
        path=str(dest_path),
        format=actual_fmt,
        size_bytes=size_bytes,
        sha256=dest_sha256,
        md5=dest_md5,
        acquired_utc=utc_now_iso(),
        verified=verified,
    )
