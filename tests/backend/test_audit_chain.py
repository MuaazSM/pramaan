"""Chain-of-custody verification (docs/02-BACKEND.md §8, §12: "Tampering any
stored entry makes verify report the exact seq").

Builds an independent copy of the fixture dataset (``generate.build()``,
not the shared ``store.DATA`` singleton) so tampering here can never leak
into other tests.
"""

from __future__ import annotations

from pramaan_api.fixtures import generate, store
from pramaan_api.fixtures.store import verify_chain


def test_untampered_chain_verifies_ok() -> None:
    data = generate.build()
    result = verify_chain(data.audit_log)
    assert result.ok is True
    assert result.length == len(data.audit_log)
    assert result.first_bad_seq is None
    assert result.head_hash == data.audit_log[-1].entry_hash


def test_tampering_an_entry_is_detected_at_the_right_seq() -> None:
    data = generate.build()
    tampered_index = 40
    victim = data.audit_log[tampered_index]
    corrupted = victim.model_copy(update={"action": "something.else"})
    entries = list(data.audit_log)
    entries[tampered_index] = corrupted

    result = verify_chain(entries)
    assert result.ok is False
    assert result.first_bad_seq == victim.seq


def test_broken_prev_hash_link_is_detected() -> None:
    data = generate.build()
    entries = list(data.audit_log)
    entries[10] = entries[10].model_copy(update={"prev_hash": "not-the-real-prev-hash"})

    result = verify_chain(entries)
    assert result.ok is False
    assert result.first_bad_seq == entries[10].seq


def test_verify_audit_endpoint_matches_verify_chain() -> None:
    via_endpoint = store.verify_audit(store.DATA.case.id)
    via_pure_function = verify_chain(store.DATA.audit_log)
    assert via_endpoint == via_pure_function
