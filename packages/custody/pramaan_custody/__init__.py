"""Hash-chained audit log, Ed25519 signing/verification, Merkle anchoring.

Public API (docs/02-BACKEND.md §8):

- ``keys``: ``load_or_create_keypair``, ``public_key_hex``, ``sign``, ``verify``.
- ``chain``: ``CustodyEntry``, ``append_entry``, ``read_chain``, ``read_chain_jsonl``,
  ``chain_jsonl_path``.
- ``chain_verify``: ``VerifyResult``, ``verify_chain`` (module deliberately not named
  ``verify`` — that name is already ``keys.verify``, the signature check).
- ``merkle``: ``merkle_root``.
- ``anchor``: ``Anchor`` (protocol), ``AnchorRecord``, ``LocalAnchor``,
  ``FabricAnchor`` (not implemented — see docs/progress/B1.md), ``verify_local_ledger``.
"""

from __future__ import annotations

from pramaan_custody.anchor import (
    Anchor,
    AnchorRecord,
    FabricAnchor,
    LocalAnchor,
    verify_local_ledger,
)
from pramaan_custody.chain import (
    CustodyEntry,
    append_entry,
    chain_jsonl_path,
    read_chain,
    read_chain_jsonl,
)
from pramaan_custody.chain_verify import VerifyResult, verify_chain
from pramaan_custody.keys import load_or_create_keypair, public_key_hex, sign, verify
from pramaan_custody.merkle import merkle_root

__version__ = "0.1.0"

__all__ = [
    "Anchor",
    "AnchorRecord",
    "CustodyEntry",
    "FabricAnchor",
    "LocalAnchor",
    "VerifyResult",
    "append_entry",
    "chain_jsonl_path",
    "load_or_create_keypair",
    "merkle_root",
    "public_key_hex",
    "read_chain",
    "read_chain_jsonl",
    "sign",
    "verify",
    "verify_chain",
    "verify_local_ledger",
]
