"""``packages/custody`` unit tests (docs/02-BACKEND.md §8, §12): the hash
chain, Ed25519 signing/verification, JSONL mirror and Merkle anchoring, in
isolation from the API layer.
"""

from __future__ import annotations

import threading
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pramaan_core.db import open_case
from pramaan_custody import (
    LocalAnchor,
    append_entry,
    load_or_create_keypair,
    merkle_root,
    public_key_hex,
    read_chain,
    read_chain_jsonl,
    sign,
    verify,
    verify_chain,
    verify_local_ledger,
)


def test_append_and_verify_chain(tmp_path: Path) -> None:
    case_dir = tmp_path / "case1"
    conn = open_case(case_dir)
    key = load_or_create_keypair(tmp_path / "keys", "examiner")
    pub = public_key_hex(key)

    e1 = append_entry(
        conn,
        case_dir,
        actor="examiner",
        role="examiner",
        action="evidence.registered",
        object_type="evidence",
        object_id="img_1",
        signing_key=key,
        payload_sha256="a" * 64,
    )
    e2 = append_entry(
        conn,
        case_dir,
        actor="examiner",
        role="examiner",
        action="evidence.verified",
        object_type="evidence",
        object_id="img_1",
        signing_key=key,
    )
    assert e1.seq == 1
    assert e2.seq == 2
    assert e2.prev_hash == e1.entry_hash

    entries = read_chain(conn)
    assert entries == [e1, e2]
    result = verify_chain(entries, pubkeys={"examiner": pub})
    assert result.ok
    assert result.head_hash == e2.entry_hash
    assert result.first_bad_seq is None

    # JSONL mirror matches the DB copy exactly.
    assert read_chain_jsonl(case_dir) == entries


def test_tampering_a_field_is_caught_at_the_right_seq(tmp_path: Path) -> None:
    case_dir = tmp_path / "case2"
    conn = open_case(case_dir)
    key = load_or_create_keypair(tmp_path / "keys", "examiner")
    for i in range(3):
        append_entry(
            conn,
            case_dir,
            actor="examiner",
            role="examiner",
            action=f"step.{i}",
            object_type="evidence",
            object_id="img_1",
            signing_key=key,
        )
    entries = read_chain(conn)
    tampered = list(entries)
    tampered[1] = tampered[1].__class__(**{**tampered[1].__dict__, "action": "tampered"})

    result = verify_chain(tampered)
    assert not result.ok
    assert result.first_bad_seq == entries[1].seq


def test_tampering_a_signature_is_caught_when_pubkeys_given(tmp_path: Path) -> None:
    case_dir = tmp_path / "case3"
    conn = open_case(case_dir)
    key = load_or_create_keypair(tmp_path / "keys", "examiner")
    other_key = load_or_create_keypair(tmp_path / "keys", "someone_else")
    entry = append_entry(
        conn,
        case_dir,
        actor="examiner",
        role="examiner",
        action="evidence.registered",
        object_type="evidence",
        object_id="img_1",
        signing_key=key,
    )
    # Hash-chain fields are untouched, but the signature doesn't match the
    # claimed actor's *real* key (forged/wrong-key signature).
    forged = entry.__class__(
        **{**entry.__dict__, "signature": sign(other_key, entry.entry_hash.encode())}
    )

    ok_pubkey = public_key_hex(key)
    result = verify_chain([forged], pubkeys={"examiner": ok_pubkey})
    assert not result.ok
    assert result.first_bad_seq == entry.seq

    # Without pubkeys, only the hash chain is checked — signature forgery
    # alone isn't detectable (matches verify_chain's documented contract).
    assert verify_chain([forged]).ok


def test_broken_prev_hash_link_detected(tmp_path: Path) -> None:
    case_dir = tmp_path / "case4"
    conn = open_case(case_dir)
    key = load_or_create_keypair(tmp_path / "keys", "examiner")
    for i in range(3):
        append_entry(
            conn,
            case_dir,
            actor="examiner",
            role="examiner",
            action=f"step.{i}",
            object_type="evidence",
            object_id="img_1",
            signing_key=key,
        )
    entries = read_chain(conn)
    tampered = list(entries)
    tampered[2] = tampered[2].__class__(
        **{**tampered[2].__dict__, "prev_hash": "not-the-real-prev-hash"}
    )
    result = verify_chain(tampered)
    assert not result.ok
    assert result.first_bad_seq == entries[2].seq


def test_sign_and_verify_roundtrip(tmp_path: Path) -> None:
    key = load_or_create_keypair(tmp_path / "keys", "examiner")
    pub = public_key_hex(key)
    sig = sign(key, b"hello")
    assert verify(pub, b"hello", sig)
    assert not verify(pub, b"goodbye", sig)


def test_keypair_is_created_once_and_reused(tmp_path: Path) -> None:
    keys_dir = tmp_path / "keys"
    key1 = load_or_create_keypair(keys_dir, "examiner")
    key2 = load_or_create_keypair(keys_dir, "examiner")
    assert public_key_hex(key1) == public_key_hex(key2)
    key_file = keys_dir / "examiner.ed25519"
    assert key_file.exists()
    assert (key_file.stat().st_mode & 0o777) == 0o600


def test_load_or_create_keypair_is_race_safe_under_concurrent_first_use(tmp_path: Path) -> None:
    """FIX-4 bug 2: `load_or_create_keypair` used to have a TOCTOU race on
    first use — two concurrent callers could each see "no key file yet",
    each generate their *own* keypair, and each write it, so whichever
    write landed last silently became "the" persisted key even though an
    earlier caller had already signed something with the other one
    (docs/progress/F4.md: custody signature verification failing from
    entry #1 on fresh data). Every one of many concurrent first-use
    callers must converge on the single persisted keypair, and a signature
    made with each caller's own returned key object must verify against
    that persisted key.
    """
    keys_dir = tmp_path / "keys"
    n = 32
    results: list[Ed25519PrivateKey | None] = [None] * n
    barrier = threading.Barrier(n)

    def _worker(i: int) -> None:
        barrier.wait()  # maximise concurrent "file doesn't exist yet" contention
        results[i] = load_or_create_keypair(keys_dir, "examiner")

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    persisted_pub = public_key_hex(load_or_create_keypair(keys_dir, "examiner"))

    for key in results:
        assert key is not None
        assert public_key_hex(key) == persisted_pub

    # Not just equal in hex -- each thread's own key object must produce a
    # signature that verifies against the one persisted public key.
    for i, key in enumerate(results):
        assert key is not None
        message = f"entry-{i}".encode()
        sig = sign(key, message)
        assert verify(persisted_pub, message, sig)


def test_merkle_root_matches_manual_pairwise_hash() -> None:
    import hashlib

    leaves = [hashlib.sha256(f"leaf-{i}".encode()).hexdigest() for i in range(3)]
    root = merkle_root(leaves)

    level = [bytes.fromhex(h) for h in leaves]
    level.append(level[-1])  # odd count -> duplicate last leaf
    level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    expected = hashlib.sha256(level[0] + level[1]).digest().hex()
    assert root == expected


def test_local_anchor_ledger_is_hash_chained(tmp_path: Path) -> None:
    ledger_path = tmp_path / "anchors" / "ledger.jsonl"
    lab_key = load_or_create_keypair(tmp_path / "keys", "lab")
    anchor = LocalAnchor(ledger_path, lab_signing_key=lab_key)

    hashes = {i: f"{i:064x}" for i in range(1, 6)}
    record1 = anchor.create("case_x", hashes, 1, 3)
    record2 = anchor.create("case_x", hashes, 4, 5)

    assert record1.merkle_root == merkle_root([hashes[1], hashes[2], hashes[3]])
    assert record2.merkle_root == merkle_root([hashes[4], hashes[5]])
    assert record1.lab_signature and record2.lab_signature
    assert verify_local_ledger(ledger_path)

    # Tamper with the ledger file directly -> chain no longer verifies.
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    import json

    corrupted = json.loads(lines[0])
    corrupted["merkle_root"] = "0" * 64
    lines[0] = json.dumps(corrupted)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not verify_local_ledger(ledger_path)
