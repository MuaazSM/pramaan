"""Full case lifecycle over the real API (docs/05-INFRA-QA.md §6):
register evidence -> scan -> recordings/frames -> report -> signed export ->
export verification, on ``hiksim_format.img`` (Tier A, deleted footage) and
``xsim_unknown.img`` (Tier B, no index — blind inference).

Marked ``slow`` (real scans against real images); run via
``uv run pytest tests/e2e -m slow`` or ``just e2e``.
"""

from __future__ import annotations

import time

import httpx
import pytest

# conftest.py (same directory, auto-loaded by pytest before this module) puts
# tools/validate on sys.path and defines these; imported directly (not via a
# `tests.e2e` package import, since tests/ has no __init__.py — see
# docs/PROMPTBOOK.md convention of flat, non-package test modules).
from conftest import CORPUS_IMAGES, RealApi, create_case, register_and_scan

pytestmark = pytest.mark.slow


def test_hiksim_format_full_lifecycle(real_api: RealApi, client: httpx.Client) -> None:
    case = create_case(client, "E2E-hiksim-format")
    case_id = case["id"]
    deadline = time.monotonic() + 300.0

    evidence, job = register_and_scan(
        client, case_id, CORPUS_IMAGES / "hiksim_format.img", deadline
    )
    assert job["status"] == "done", job

    recordings = client.get(f"/api/cases/{case_id}/recordings").json()
    assert len(recordings) > 0

    matches = client.get(f"/api/evidence/{evidence['id']}/fingerprint").json()
    assert any(m["family"] == "hiksim" for m in matches)

    deletions = client.get(f"/api/cases/{case_id}/deletions").json()
    assert len(deletions) > 0

    # --- report -----------------------------------------------------
    report_resp = client.post(f"/api/cases/{case_id}/reports", json={}, headers=_csrf(client))
    assert report_resp.status_code == 201, report_resp.text
    report = report_resp.json()
    assert report["report_sha256"]

    pdf_resp = client.get(f"/api/reports/{report['id']}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content[:4] in (b"%PDF", b"%PDF"[:4])

    # --- signed export + verification --------------------------------
    live = [r for r in recordings if not r["deleted"]]
    assert live, "expected at least one live recording to export"
    export_resp = client.post(
        f"/api/cases/{case_id}/exports",
        json={"recording_id": live[0]["id"]},
        headers=_csrf(client),
    )
    assert export_resp.status_code == 201, export_resp.text
    export = export_resp.json()

    file_resp = client.get(f"/api/exports/{export['id']}/file")
    assert file_resp.status_code == 200
    assert len(file_resp.content) > 0

    verify_resp = client.post(
        "/api/exports/verify",
        files={"file": ("export.mp4", file_resp.content, "video/mp4")},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    result = verify_resp.json()
    assert result["signature_valid"] is True
    assert result["source_matches_registered_evidence"] is True


def test_xsim_unknown_full_lifecycle(real_api: RealApi, client: httpx.Client) -> None:
    """Tier B, no index: identification + blind inference + recovered
    frames, no live-recording export expected (xsim_unknown has no live
    index-sourced recording — docs/01-FORENSIC-CORE.md §4.8)."""
    case = create_case(client, "E2E-xsim-unknown")
    case_id = case["id"]
    deadline = time.monotonic() + 300.0

    evidence, job = register_and_scan(client, case_id, CORPUS_IMAGES / "xsim_unknown.img", deadline)
    assert job["status"] == "done", job

    matches = client.get(f"/api/evidence/{evidence['id']}/fingerprint").json()
    assert any(m["family"] == "xsim" for m in matches)

    frames = client.get(f"/api/cases/{case_id}/frames", params={"limit": 500}).json()
    assert len(frames) > 0

    layout = client.get(f"/api/evidence/{evidence['id']}/inferred-layout")
    assert layout.status_code == 200
    assert layout.json()["header_len"] > 0

    report_resp = client.post(f"/api/cases/{case_id}/reports", json={}, headers=_csrf(client))
    assert report_resp.status_code == 201, report_resp.text


def _csrf(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("pramaan_csrf")
    assert token, "no CSRF cookie set — did the client fixture log in?"
    return {"x-csrf-token": token}
