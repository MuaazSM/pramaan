"""Provenance helper tests."""

from __future__ import annotations

from pramaan_core.provenance import make_provenance


def test_make_provenance_fields() -> None:
    prov = make_provenance(
        "recovery.carve_annexb", {"b": 2, "a": 1}, parent_sha256="a" * 64
    )
    assert prov.tool == "pramaan"
    assert prov.step == "recovery.carve_annexb"
    assert prov.parent_sha256 == "a" * 64
    assert prov.params == {"a": 1, "b": 2}
    assert prov.tool_version
    assert prov.created_utc


def test_make_provenance_default_parent_is_none() -> None:
    prov = make_provenance("core.acquire", {})
    assert prov.parent_sha256 is None


def test_make_provenance_fixed_created_utc() -> None:
    prov = make_provenance("core.acquire", {}, created_utc="2026-01-01T00:00:00Z")
    assert prov.created_utc == "2026-01-01T00:00:00Z"
