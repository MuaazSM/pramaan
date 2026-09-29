"""Path traversal / out-of-root evidence paths must be rejected
(docs/02-BACKEND.md §11, §12).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_register_evidence_outside_evidence_roots_rejected(
    examiner_client: TestClient, case_id: str
) -> None:
    body = {
        "path": "/etc/passwd",
        "label": "not evidence",
        "intake": {
            "seized_at_local": "2026-03-12T16:40:00+05:30",
            "dvr_displayed_time": "2026-03-12T16:45:12",
            "reference_time": "2026-03-12T16:40:00+05:30",
            "reference_source": "NTP phone clock",
            "timezone": "Asia/Kolkata",
        },
    }
    resp = examiner_client.post(f"/api/cases/{case_id}/evidence", json=body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_register_evidence_traversal_outside_root_rejected(
    examiner_client: TestClient, case_id: str
) -> None:
    body = {
        "path": "/evidence/../etc/passwd",
        "label": "traversal attempt",
        "intake": {
            "seized_at_local": "2026-03-12T16:40:00+05:30",
            "dvr_displayed_time": "2026-03-12T16:45:12",
            "reference_time": "2026-03-12T16:40:00+05:30",
            "reference_source": "NTP phone clock",
            "timezone": "Asia/Kolkata",
        },
    }
    resp = examiner_client.post(f"/api/cases/{case_id}/evidence", json=body)
    assert resp.status_code == 400


def test_fs_browse_outside_evidence_roots_returns_empty(examiner_client: TestClient) -> None:
    resp = examiner_client.get("/api/fs/browse", params={"path": "/etc"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_fs_browse_within_evidence_roots_lists_entries(examiner_client: TestClient) -> None:
    resp = examiner_client.get("/api/fs/browse", params={"path": "/evidence"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
