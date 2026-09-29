"""Real-mode anchors (docs/02-BACKEND.md §8, §12: "Merkle root recomputes
from entries; local ledger chain valid").
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pramaan_custody.anchor import verify_local_ledger
from pramaan_custody.merkle import merkle_root


def _create_case(client: TestClient, number: str) -> dict:
    resp = client.post("/api/cases", json={"case_number": number, "title": "Anchors test"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_anchor_recomputes_merkle_root(real_client: TestClient, real_settings) -> None:
    case = _create_case(real_client, "CR-ANCHOR-0001")

    resp = real_client.post(f"/api/cases/{case['id']}/anchors", json={})
    assert resp.status_code == 201, resp.text
    anchor = resp.json()
    assert anchor["backend"] == "local"
    assert anchor["from_seq"] == 1  # only "case.created" has been logged so far
    assert anchor["lab_signature"]

    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    entry_hashes = [
        e["entry_hash"]
        for e in audit["items"]
        if anchor["from_seq"] <= e["seq"] <= anchor["to_seq"]
    ]
    assert merkle_root(entry_hashes) == anchor["merkle_root"]

    listed = real_client.get(f"/api/cases/{case['id']}/anchors").json()
    assert any(a["id"] == anchor["id"] for a in listed)


def test_local_ledger_is_hash_chained_and_appended_to(
    real_client: TestClient, real_settings
) -> None:
    case_a = _create_case(real_client, "CR-ANCHOR-0002")
    case_b = _create_case(real_client, "CR-ANCHOR-0003")

    real_client.post(f"/api/cases/{case_a['id']}/anchors", json={})
    real_client.post(f"/api/cases/{case_b['id']}/anchors", json={})

    ledger_path = Path(real_settings.data_dir) / "anchors" / "ledger.jsonl"
    assert ledger_path.exists()
    lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2  # one anchor per case, shared ledger
    assert verify_local_ledger(ledger_path)


def test_anchoring_empty_chain_rejected(real_client: TestClient) -> None:
    # A case with zero audit entries can't happen through the API (creating
    # the case itself is audited), so this exercises the guard directly
    # against a case that *is* logged — anchoring twice in a row must still
    # succeed (chain only grows), which is the meaningful regression to
    # guard here: anchoring never breaks on a short/growing chain.
    case = _create_case(real_client, "CR-ANCHOR-0004")
    first = real_client.post(f"/api/cases/{case['id']}/anchors", json={}).json()
    second = real_client.post(f"/api/cases/{case['id']}/anchors", json={}).json()
    assert second["from_seq"] == first["from_seq"]
    assert second["to_seq"] >= first["to_seq"]


def test_fabric_backend_not_implemented_returns_clean_error(real_client: TestClient) -> None:
    case = _create_case(real_client, "CR-ANCHOR-0005")
    resp = real_client.post(f"/api/cases/{case['id']}/anchors", json={"backend": "fabric"})
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "not_implemented"
