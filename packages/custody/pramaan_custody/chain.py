"""The hash-chained custody log itself (docs/02-BACKEND.md §8).

``append_entry`` is the single place a mutating action becomes a custody
entry: it reads the current chain tail from ``audit_log`` (SQLite), builds
the canonical unsigned record, hashes it, signs the hash with the acting
examiner's Ed25519 key, inserts the row, and mirrors it append-only to
``<case_dir>/custody/chain.jsonl``. Both writes happen under the caller-
supplied lock (custody entries must be strictly ordered by ``seq``).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pramaan_core.ids import canonical_json, content_hash
from pramaan_core.timeutil import utc_now_iso

from pramaan_custody.keys import sign


@dataclass(frozen=True)
class CustodyEntry:
    seq: int
    prev_hash: str | None
    entry_hash: str
    ts_utc: str
    actor: str
    role: str
    action: str
    object_type: str
    object_id: str
    payload_sha256: str | None
    details: dict[str, Any]
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "ts_utc": self.ts_utc,
            "actor": self.actor,
            "role": self.role,
            "action": self.action,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "payload_sha256": self.payload_sha256,
            "details": self.details,
            "signature": self.signature,
        }


def _unsigned_fields(
    *,
    seq: int,
    prev_hash: str | None,
    ts_utc: str,
    actor: str,
    role: str,
    action: str,
    object_type: str,
    object_id: str,
    payload_sha256: str | None,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "seq": seq,
        "prev_hash": prev_hash,
        "ts_utc": ts_utc,
        "actor": actor,
        "role": role,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "payload_sha256": payload_sha256,
        "details": details,
    }


def chain_jsonl_path(case_dir: Path) -> Path:
    return case_dir / "custody" / "chain.jsonl"


def _chain_tail(conn: sqlite3.Connection) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    return row


def append_entry(
    conn: sqlite3.Connection,
    case_dir: Path,
    *,
    actor: str,
    role: str,
    action: str,
    object_type: str,
    object_id: str,
    signing_key: Ed25519PrivateKey,
    payload_sha256: str | None = None,
    details: dict[str, Any] | None = None,
    ts_utc: str | None = None,
) -> CustodyEntry:
    """Append one custody entry to ``audit_log`` and the JSONL mirror.

    Callers must hold whatever lock guards ``conn`` for this case — ``seq``
    is computed as ``MAX(seq) + 1`` and must never race another writer.

    That in-process lock only protects concurrent *threads*; two separate
    processes sharing the same case dir (task FIX-4 / FIX-2 "Cross-
    workstream issues" #3: two concurrent ``just demo`` runs against the
    same ``data/demo/``) each get their own connection and their own lock,
    so the tail read and the insert weren't atomic across processes —
    observed as ``sqlite3.IntegrityError: UNIQUE constraint failed:
    audit_log.seq``. An explicit ``BEGIN IMMEDIATE`` (skipped if the
    connection is already mid-transaction, so this stays a no-op for any
    caller that already manages its own) acquires SQLite's RESERVED lock
    before the tail ``SELECT`` runs rather than only before the ``INSERT``
    (all Python's own implicit-transaction handling would otherwise
    cover), so a second process's own ``BEGIN IMMEDIATE`` blocks until this
    one commits (both ``pramaan_core.db.open_case`` and
    ``pramaan_api.real.appdb``'s connections set a busy timeout, so that
    second writer waits instead of raising immediately).
    """
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute("BEGIN IMMEDIATE")
    tail = _chain_tail(conn)
    seq = (int(tail["seq"]) + 1) if tail is not None else 1
    prev_hash = str(tail["entry_hash"]) if tail is not None else None
    ts = ts_utc or utc_now_iso()
    details = details or {}

    unsigned = _unsigned_fields(
        seq=seq,
        prev_hash=prev_hash,
        ts_utc=ts,
        actor=actor,
        role=role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        payload_sha256=payload_sha256,
        details=details,
    )
    entry_hash = content_hash(unsigned)
    signature = sign(signing_key, entry_hash.encode("ascii"))
    entry = CustodyEntry(
        seq=seq,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        ts_utc=ts,
        actor=actor,
        role=role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        payload_sha256=payload_sha256,
        details=details,
        signature=signature,
    )

    conn.execute(
        "INSERT INTO audit_log "
        "(id, seq, prev_hash, entry_hash, ts_utc, actor, role, action, object_type, "
        " object_id, payload_sha256, details, signature) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            entry.entry_hash,
            entry.seq,
            entry.prev_hash,
            entry.entry_hash,
            entry.ts_utc,
            entry.actor,
            entry.role,
            entry.action,
            entry.object_type,
            entry.object_id,
            entry.payload_sha256,
            json.dumps(entry.details, sort_keys=True),
            entry.signature,
        ),
    )
    conn.commit()

    jsonl_path = chain_jsonl_path(case_dir)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as fh:
        fh.write(canonical_json(entry.to_dict()).decode("utf-8") + "\n")

    return entry


def read_chain(conn: sqlite3.Connection) -> list[CustodyEntry]:
    rows = conn.execute(
        "SELECT seq, prev_hash, entry_hash, ts_utc, actor, role, action, object_type, "
        "object_id, payload_sha256, details, signature FROM audit_log ORDER BY seq ASC"
    ).fetchall()
    return [
        CustodyEntry(
            seq=row["seq"],
            prev_hash=row["prev_hash"],
            entry_hash=row["entry_hash"],
            ts_utc=row["ts_utc"],
            actor=row["actor"],
            role=row["role"],
            action=row["action"],
            object_type=row["object_type"],
            object_id=row["object_id"],
            payload_sha256=row["payload_sha256"],
            details=json.loads(row["details"]),
            signature=row["signature"],
        )
        for row in rows
    ]


def read_chain_jsonl(case_dir: Path) -> list[CustodyEntry]:
    """Read the append-only JSONL mirror back into entries (used by tests
    and by anything that wants to verify the mirror independently of the
    SQLite copy).
    """
    path = chain_jsonl_path(case_dir)
    if not path.exists():
        return []
    entries: list[CustodyEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        entries.append(
            CustodyEntry(
                seq=row["seq"],
                prev_hash=row["prev_hash"],
                entry_hash=row["entry_hash"],
                ts_utc=row["ts_utc"],
                actor=row["actor"],
                role=row["role"],
                action=row["action"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                payload_sha256=row["payload_sha256"],
                details=row["details"],
                signature=row["signature"],
            )
        )
    return entries
