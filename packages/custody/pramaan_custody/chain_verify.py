"""Chain verification (docs/02-BACKEND.md §8, §12: "Tampering any stored
entry makes verify report the exact seq; signatures validate").
"""

from __future__ import annotations

from dataclasses import dataclass

from pramaan_core.ids import content_hash

from pramaan_custody.chain import CustodyEntry
from pramaan_custody.keys import verify as verify_signature


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    length: int
    head_hash: str | None
    first_bad_seq: int | None


def verify_chain(
    entries: list[CustodyEntry], pubkeys: dict[str, str] | None = None
) -> VerifyResult:
    """Recompute every ``entry_hash`` and hash-chain link; when ``pubkeys``
    (actor -> hex Ed25519 public key) is given, also verify each entry's
    signature. Returns the first broken ``seq``, if any.
    """
    if not entries:
        return VerifyResult(ok=True, length=0, head_hash=None, first_bad_seq=None)

    prev_hash: str | None = None
    for entry in entries:
        unsigned = {
            "seq": entry.seq,
            "prev_hash": entry.prev_hash,
            "ts_utc": entry.ts_utc,
            "actor": entry.actor,
            "role": entry.role,
            "action": entry.action,
            "object_type": entry.object_type,
            "object_id": entry.object_id,
            "payload_sha256": entry.payload_sha256,
            "details": entry.details,
        }
        expected_hash = content_hash(unsigned)
        hash_ok = entry.prev_hash == prev_hash and entry.entry_hash == expected_hash

        sig_ok = True
        if pubkeys is not None:
            pubkey = pubkeys.get(entry.actor)
            sig_ok = pubkey is not None and verify_signature(
                pubkey, entry.entry_hash.encode("ascii"), entry.signature
            )

        if not (hash_ok and sig_ok):
            return VerifyResult(
                ok=False, length=len(entries), head_hash=None, first_bad_seq=entry.seq
            )
        prev_hash = entry.entry_hash

    return VerifyResult(ok=True, length=len(entries), head_hash=prev_hash, first_bad_seq=None)
