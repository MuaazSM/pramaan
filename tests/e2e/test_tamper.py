"""Tamper detection (docs/05-INFRA-QA.md §6): flip a byte in a copy of
evidence / an exported MP4 / the custody chain database and confirm the
product's own verification catches it. Never mutates a corpus fixture in
place — evidence tamper tests operate on a writable *copy* under
``data/e2e/tamper_root`` (CLAUDE.md rule 1: evidence is read-only; the
*harness's own copy* is what gets flipped, exactly the way a real
tamper/corruption event would land on disk before an examiner re-verifies).

Marked ``slow`` (real scans against real images); run via
``uv run pytest tests/e2e -m slow`` or ``just e2e``.
"""

from __future__ import annotations

import shutil
import time

import api_client as api
import httpx
import pytest
from conftest import (
    CORPUS_IMAGES,
    RealApi,
    create_case,
    flip_one_byte,
    register_and_scan,
    tamper_audit_entry,
)

pytestmark = pytest.mark.slow


def _csrf(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("pramaan_csrf")
    assert token, "no CSRF cookie set — did the client fixture log in?"
    return {"x-csrf-token": token}


def test_evidence_tamper_causes_verify_to_fail(real_api: RealApi, client: httpx.Client) -> None:
    tamper_copy = real_api.tamper_root / "tamper_evidence.img"
    shutil.copyfile(CORPUS_IMAGES / "hiksim_clean.img", tamper_copy)

    case = create_case(client, "E2E-tamper-evidence")
    case_id = case["id"]
    deadline = time.monotonic() + 300.0
    evidence, job = register_and_scan(client, case_id, tamper_copy, deadline)
    assert job["status"] == "done", job

    # Sanity: verify passes on the untampered copy first.
    ok_job = api.run_job(client, evidence["id"], "verify")
    ok_job = api.poll_job(client, ok_job["id"], deadline)
    assert ok_job["status"] == "done", ok_job

    flip_one_byte(tamper_copy)

    bad_job = api.run_job(client, evidence["id"], "verify")
    bad_job = api.poll_job(client, bad_job["id"], deadline)
    assert bad_job["status"] == "failed", bad_job
    hash_stage = next(s for s in bad_job["stages"] if s["name"] == "hash_verify")
    assert hash_stage["status"] == "failed"
    assert "mismatch" in (hash_stage.get("message") or "").lower()


def test_export_tamper_fails_verification(real_api: RealApi, client: httpx.Client) -> None:
    case = create_case(client, "E2E-tamper-export")
    case_id = case["id"]
    deadline = time.monotonic() + 300.0
    evidence, job = register_and_scan(
        client, case_id, CORPUS_IMAGES / "hiksim_format.img", deadline
    )
    assert job["status"] == "done", job

    recordings = client.get(f"/api/cases/{case_id}/recordings").json()
    live = [r for r in recordings if not r["deleted"]]
    assert live

    export = client.post(
        f"/api/cases/{case_id}/exports", json={"recording_id": live[0]["id"]}, headers=_csrf(client)
    ).json()
    file_resp = client.get(f"/api/exports/{export['id']}/file")
    assert file_resp.status_code == 200
    original = bytearray(file_resp.content)
    assert len(original) > 4096, "export unexpectedly tiny — tamper offset would be out of range"

    # Sanity: an untampered round trip verifies clean.
    ok_resp = client.post(
        "/api/exports/verify", files={"file": ("export.mp4", bytes(original), "video/mp4")}
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["signature_valid"] is True

    tampered = bytearray(original)
    tampered[4096] ^= (
        0xFF  # well inside the muxed video payload, before the trailing manifest/sig boxes
    )
    bad_resp = client.post(
        "/api/exports/verify", files={"file": ("export.mp4", bytes(tampered), "video/mp4")}
    )
    assert bad_resp.status_code == 200
    result = bad_resp.json()
    assert result["signature_valid"] is False


def test_custody_chain_tamper_causes_verify_to_fail(
    real_api: RealApi, client: httpx.Client
) -> None:
    case = create_case(client, "E2E-tamper-custody")
    case_id = case["id"]
    deadline = time.monotonic() + 300.0
    _evidence, job = register_and_scan(
        client, case_id, CORPUS_IMAGES / "hiksim_clean.img", deadline
    )
    assert job["status"] == "done", job

    ok = client.get(f"/api/cases/{case_id}/audit/verify").json()
    assert ok["ok"] is True
    assert ok["length"] >= 1

    tamper_audit_entry(real_api.case_db_path(case_id), seq=1)

    bad = client.get(f"/api/cases/{case_id}/audit/verify").json()
    assert bad["ok"] is False
    assert bad["first_bad_seq"] == 1
