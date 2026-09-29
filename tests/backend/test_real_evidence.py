"""Real (non-fixture) mode: cases, evidence registration, jobs, custody
(task B1, docs/02-BACKEND.md §5-8, §12).

Acceptance (02 §12 / docs/PROMPTBOOK.md B1): "registering a generated file
hashes it and appends audit entries visible via /audit."
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def _intake_body() -> dict[str, str]:
    return {
        "seized_at_local": "2026-03-12T16:40:00+05:30",
        "dvr_displayed_time": "2026-03-12T16:45:12",
        "reference_time": "2026-03-12T16:40:00+05:30",
        "reference_source": "NTP phone clock",
        "timezone": "Asia/Kolkata",
        "make_model_label": "Hikvision DS-7208 (synthetic)",
        "notes": "Device time not changed",
    }


def _make_evidence_file(evidence_dir: Path, name: str = "device.raw", size: int = 65536) -> Path:
    path = evidence_dir / name
    data = bytes((i * 7 + 3) % 256 for i in range(size))
    path.write_bytes(data)
    return path


def _create_case(client: TestClient, number: str) -> dict:
    resp = client.post(
        "/api/cases", json={"case_number": number, "title": f"Real-mode case {number}"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_list_case_real_mode(real_client: TestClient) -> None:
    case = _create_case(real_client, "CR-REAL-0001")
    assert case["case_number"] == "CR-REAL-0001"
    assert case["status"] == "open"

    listed = real_client.get("/api/cases").json()
    assert any(c["id"] == case["id"] for c in listed)

    fetched = real_client.get(f"/api/cases/{case['id']}").json()
    assert fetched == case

    patched = real_client.patch(f"/api/cases/{case['id']}", json={"status": "closed"}).json()
    assert patched["status"] == "closed"


def test_register_evidence_hashes_real_file_and_appends_audit(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0002")
    file_path = _make_evidence_file(real_evidence_dir)
    expected_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()

    resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "Test drive", "intake": _intake_body()},
    )
    assert resp.status_code == 201, resp.text
    image = resp.json()
    assert image["sha256"] == expected_sha256
    assert image["format"] == "raw"
    assert image["verified"] is True
    assert image["size_bytes"] == file_path.stat().st_size

    fetched = real_client.get(f"/api/evidence/{image['id']}").json()
    assert fetched == image

    listed = real_client.get(f"/api/cases/{case['id']}/evidence").json()
    assert any(e["id"] == image["id"] for e in listed)

    # audit entries visible via /audit (docs/02-BACKEND.md §8/§12)
    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    assert "case.created" in actions
    assert "evidence.registered" in actions
    registered_entry = next(e for e in audit["items"] if e["action"] == "evidence.registered")
    assert registered_entry["payload_sha256"] == expected_sha256
    assert registered_entry["object_id"] == image["id"]
    assert registered_entry["actor"] == "examiner"
    assert registered_entry["signature"]

    # chain verifies end to end (hash links + Ed25519 signatures)
    verify = real_client.get(f"/api/cases/{case['id']}/audit/verify").json()
    assert verify["ok"] is True
    assert verify["first_bad_seq"] is None
    assert verify["length"] == len(audit["items"])


def test_registering_same_bytes_twice_is_idempotent(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0003")
    file_path = _make_evidence_file(real_evidence_dir, "dup.raw")

    first = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "first", "intake": _intake_body()},
    ).json()
    second = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "second", "intake": _intake_body()},
    ).json()
    assert first["id"] == second["id"]  # content-derived id — same bytes, same id


def test_verify_job_rehashes_and_updates_evidence(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0004")
    file_path = _make_evidence_file(real_evidence_dir, "verify.raw")
    image = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "x", "intake": _intake_body()},
    ).json()

    resp = real_client.post(f"/api/evidence/{image['id']}/verify")
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["kind"] == "verify"
    assert job["status"] == "done"
    assert len(job["stages"]) == 1
    assert job["stages"][0]["name"] == "hash_verify"
    assert job["stages"][0]["status"] == "done"
    assert job["stages"][0]["pct"] == 100.0
    assert image["sha256"] in job["stages"][0]["message"]

    fetched_job = real_client.get(f"/api/jobs/{job['id']}").json()
    assert fetched_job["status"] == "done"

    fetched_image = real_client.get(f"/api/evidence/{image['id']}").json()
    assert fetched_image["verified"] is True

    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    assert "pipeline.hash_verify" in actions


def test_scan_job_runs_every_stage(real_client: TestClient, real_evidence_dir: Path) -> None:
    case = _create_case(real_client, "CR-REAL-0005")
    file_path = _make_evidence_file(real_evidence_dir, "scan.raw")
    image = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "x", "intake": _intake_body()},
    ).json()

    resp = real_client.post(f"/api/evidence/{image['id']}/scan", json={})
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["kind"] == "scan"
    assert job["status"] == "done"
    assert len(job["stages"]) == 11
    assert all(s["status"] == "done" for s in job["stages"])
    assert job["stages"][0]["name"] == "hash_verify"


def test_reviewer_cannot_register_evidence(
    real_client: TestClient, real_reviewer_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0006")
    resp = real_reviewer_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={
            "path": str(real_evidence_dir / "whatever.raw"),
            "label": "x",
            "intake": _intake_body(),
        },
    )
    assert resp.status_code == 403


def test_evidence_registration_outside_evidence_roots_rejected(
    real_client: TestClient, tmp_path: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0007")
    outside = tmp_path / "outside.raw"
    outside.write_bytes(b"not evidence")
    resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(outside), "label": "x", "intake": _intake_body()},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_evidence_registration_traversal_rejected(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0008")
    traversal_path = str(real_evidence_dir / ".." / "escape.raw")
    resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": traversal_path, "label": "x", "intake": _intake_body()},
    )
    assert resp.status_code == 400


def test_fs_browse_real_mode_within_and_outside_root(
    real_client: TestClient, real_evidence_dir: Path, tmp_path: Path
) -> None:
    (real_evidence_dir / "a.raw").write_bytes(b"x")
    (real_evidence_dir / "sub").mkdir()

    within = real_client.get("/api/fs/browse", params={"path": str(real_evidence_dir)})
    assert within.status_code == 200
    names = {e["name"] for e in within.json()}
    assert {"a.raw", "sub"} <= names

    outside = real_client.get("/api/fs/browse", params={"path": str(tmp_path)})
    assert outside.status_code == 200
    assert outside.json() == []


def test_missing_csrf_header_rejected(real_settings, real_evidence_dir: Path) -> None:
    from pramaan_api.deps import get_settings
    from pramaan_api.main import app

    def _settings():
        return real_settings

    app.dependency_overrides[get_settings] = _settings
    try:
        with TestClient(app) as client:
            resp = client.post("/api/auth/login", json={"username": "examiner", "password": "demo"})
            assert resp.status_code == 200
            # Deliberately not echoing the CSRF cookie in a header.
            create = client.post("/api/cases", json={"case_number": "CR-REAL-0009", "title": "x"})
            assert create.status_code == 403
            assert create.json()["error"]["code"] == "csrf_failed"
    finally:
        app.dependency_overrides.pop(get_settings, None)
