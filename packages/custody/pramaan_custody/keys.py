"""Ed25519 keypairs for examiners and the lab (docs/02-BACKEND.md §8).

One key per examiner, plus one lab key (for anchors and, later, report
signing). Private keys are raw 32-byte Ed25519 seeds written with mode 600
under ``<data_dir>/keys/<name>.ed25519``; a key is generated on first use
and reused after that (idempotent — "created with the user").
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def key_path(keys_dir: Path, name: str) -> Path:
    return keys_dir / f"{name}.ed25519"


def load_or_create_keypair(keys_dir: Path, name: str) -> Ed25519PrivateKey:
    """Load ``<keys_dir>/<name>.ed25519`` (raw 32-byte seed), creating it
    (mode 600) with a freshly generated key if it doesn't exist yet.

    Atomic create-if-absent (task FIX-4 bug 2): the original
    ``exists()``-then-write had a TOCTOU race — two concurrent callers (two
    request-handling threads/processes, both hitting "key file doesn't
    exist yet" before either finished writing) could each generate a
    *different* key and both write it, so whichever wrote last silently
    became "the" key even though an earlier caller had already signed
    entries with the other one (custody chain entries then fail Ed25519
    verification against whatever key ends up on disk).

    Fixed by writing the freshly generated key to a uniquely named temp
    file in ``keys_dir`` (same directory => same filesystem, so the
    following link is atomic) and then hard-linking it onto the final
    path: ``os.link`` raises ``FileExistsError`` if another writer already
    won the race, instead of two independent writers both truncating the
    same path. Either way — created it ourselves, or lost the race — the
    function always finishes by re-reading the *persisted* file, so every
    caller converges on the single key that is actually on disk, never the
    bytes it happened to generate locally.
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    path = key_path(keys_dir, name)
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(path.read_bytes())

    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fd, tmp_name = tempfile.mkstemp(dir=str(keys_dir), prefix=f".{name}.", suffix=".tmp")
    try:
        os.write(fd, raw)
        os.close(fd)
        fd = -1
        try:
            os.link(tmp_name, str(path))
        except FileExistsError:
            # Another thread/process created `path` first -- our freshly
            # generated key is discarded; the re-read below picks up
            # whichever key actually won.
            pass
    finally:
        if fd != -1:
            os.close(fd)
        os.unlink(tmp_name)

    # Always re-read the persisted key (whether we just created it or lost
    # the race) rather than returning `private_key` directly -- this is the
    # actual fix, not just the atomic write above.
    return Ed25519PrivateKey.from_private_bytes(path.read_bytes())


def public_key_hex(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw.hex()


def sign(private_key: Ed25519PrivateKey, message: bytes) -> str:
    """Sign ``message``, returning the signature base64-encoded."""
    return base64.b64encode(private_key.sign(message)).decode("ascii")


def verify(pubkey_hex: str, message: bytes, signature_b64: str) -> bool:
    """``True`` iff ``signature_b64`` is a valid Ed25519 signature of
    ``message`` under the hex-encoded public key ``pubkey_hex``.
    """
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        public_key.verify(base64.b64decode(signature_b64), message)
    except (InvalidSignature, ValueError):
        return False
    return True
