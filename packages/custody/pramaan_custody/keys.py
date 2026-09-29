"""Ed25519 keypairs for examiners and the lab (docs/02-BACKEND.md §8).

One key per examiner, plus one lab key (for anchors and, later, report
signing). Private keys are raw 32-byte Ed25519 seeds written with mode 600
under ``<data_dir>/keys/<name>.ed25519``; a key is generated on first use
and reused after that (idempotent — "created with the user").
"""

from __future__ import annotations

import base64
import os
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
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    path = key_path(keys_dir, name)
    if path.exists():
        raw = path.read_bytes()
        return Ed25519PrivateKey.from_private_bytes(raw)

    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    return private_key


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
