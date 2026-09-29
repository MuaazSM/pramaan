"""Merkle tree over custody ``entry_hash`` values (docs/02-BACKEND.md §8).

SHA-256, duplicate the last leaf on an odd-sized level (the documented
choice — avoids second-preimage weaknesses from unbalanced trees without
needing a real "no sibling" marker).
"""

from __future__ import annotations

import hashlib


def _pair_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()


def merkle_root(leaf_hex_hashes: list[str]) -> str:
    """SHA-256 Merkle root of ``leaf_hex_hashes`` (each a hex digest, e.g.
    a custody ``entry_hash``). Deterministic; ``[]`` maps to
    ``sha256(b"")``.
    """
    if not leaf_hex_hashes:
        return hashlib.sha256(b"").hexdigest()

    level = [bytes.fromhex(h) for h in leaf_hex_hashes]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_pair_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()
