"""Anchoring (docs/02-BACKEND.md §8): ``Anchor`` protocol, ``LocalAnchor``
(append-only, itself hash-chained, ``anchors/ledger.jsonl``) and a
``FabricAnchor`` placeholder.

``FabricAnchor`` is P1 per the doc ("implement only if Docker + Fabric
samples start within 20 minutes; otherwise ship LocalAnchor, keep the
interface, and log the decision") — this task shipped ``LocalAnchor`` only;
see docs/progress/B1.md "Decisions".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pramaan_core.ids import canonical_json, content_hash
from pramaan_core.timeutil import utc_now_iso

from pramaan_custody.keys import sign
from pramaan_custody.merkle import merkle_root


@dataclass(frozen=True)
class AnchorRecord:
    id: str
    case_id: str
    merkle_root: str
    from_seq: int
    to_seq: int
    ts_utc: str
    backend: str
    lab_signature: str | None


class Anchor(Protocol):
    def create(
        self,
        case_id: str,
        entry_hashes_by_seq: dict[int, str],
        from_seq: int,
        to_seq: int,
    ) -> AnchorRecord: ...


def _unsigned_ledger_fields(
    *, case_id: str, root: str, from_seq: int, to_seq: int, ts_utc: str, prev_hash: str | None
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "merkle_root": root,
        "from_seq": from_seq,
        "to_seq": to_seq,
        "ts_utc": ts_utc,
        "prev_hash": prev_hash,
    }


class LocalAnchor:
    """Appends ``{case_id, merkle_root, from_seq, to_seq, ts_utc,
    lab_signature}`` to ``<data_dir>/anchors/ledger.jsonl``, itself hash-
    chained the same way as the custody log (``prev_hash``/``entry_hash``
    over the record's canonical JSON).
    """

    def __init__(self, ledger_path: Path, lab_signing_key: Ed25519PrivateKey | None = None) -> None:
        self._ledger_path = ledger_path
        self._lab_signing_key = lab_signing_key

    def _tail(self) -> dict[str, object] | None:
        if not self._ledger_path.exists():
            return None
        raw = self._ledger_path.read_text(encoding="utf-8")
        lines = [line for line in raw.splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else None

    def create(
        self,
        case_id: str,
        entry_hashes_by_seq: dict[int, str],
        from_seq: int,
        to_seq: int,
    ) -> AnchorRecord:
        leaves = [
            entry_hashes_by_seq[seq]
            for seq in sorted(entry_hashes_by_seq)
            if from_seq <= seq <= to_seq
        ]
        root = merkle_root(leaves)
        tail = self._tail()
        prev_hash = str(tail["entry_hash"]) if tail is not None else None
        ts = utc_now_iso()

        unsigned = _unsigned_ledger_fields(
            case_id=case_id,
            root=root,
            from_seq=from_seq,
            to_seq=to_seq,
            ts_utc=ts,
            prev_hash=prev_hash,
        )
        entry_hash = content_hash(unsigned)
        signature = (
            sign(self._lab_signing_key, entry_hash.encode("ascii"))
            if self._lab_signing_key is not None
            else None
        )
        record = {**unsigned, "entry_hash": entry_hash, "lab_signature": signature}

        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._ledger_path, "a", encoding="utf-8") as fh:
            fh.write(canonical_json(record).decode("utf-8") + "\n")

        return AnchorRecord(
            id=f"anc_{entry_hash[:16]}",
            case_id=case_id,
            merkle_root=root,
            from_seq=from_seq,
            to_seq=to_seq,
            ts_utc=ts,
            backend="local",
            lab_signature=signature,
        )


def verify_local_ledger(ledger_path: Path) -> bool:
    """Recompute the local anchor ledger's own hash chain from scratch."""
    if not ledger_path.exists():
        return True
    prev_hash: str | None = None
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        unsigned = _unsigned_ledger_fields(
            case_id=record["case_id"],
            root=record["merkle_root"],
            from_seq=record["from_seq"],
            to_seq=record["to_seq"],
            ts_utc=record["ts_utc"],
            prev_hash=record.get("prev_hash"),
        )
        expected_hash = content_hash(unsigned)
        if record.get("prev_hash") != prev_hash or record.get("entry_hash") != expected_hash:
            return False
        prev_hash = record["entry_hash"]
    return True


class FabricAnchor:
    """Placeholder for the Hyperledger Fabric backend (``pramaan-anchor``
    chaincode, ``PutAnchor(caseId, root, fromSeq, toSeq)``). Not implemented
    in this task — Docker + a running Fabric test network were not
    available/verified within the time budget; see docs/progress/B1.md
    "Decisions". Keeps the ``Anchor`` interface so wiring it up later is a
    drop-in swap behind ``ANCHOR_BACKEND=fabric``.
    """

    def create(
        self,
        case_id: str,
        entry_hashes_by_seq: dict[int, str],
        from_seq: int,
        to_seq: int,
    ) -> AnchorRecord:
        raise NotImplementedError(
            "FabricAnchor is not implemented in this environment (no Fabric test "
            "network available) — use ANCHOR_BACKEND=local. See docs/progress/B1.md."
        )
