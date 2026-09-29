from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_success_sets_session_cookie(anon_client: TestClient) -> None:
    resp = anon_client.post("/api/auth/login", json={"username": "examiner", "password": "demo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"username": "examiner", "role": "examiner", "display_name": "Examiner Demo"}
    assert "pramaan_session" in resp.cookies


def test_login_wrong_password_rejected(anon_client: TestClient) -> None:
    resp = anon_client.post("/api/auth/login", json={"username": "examiner", "password": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_login_unknown_user_rejected(anon_client: TestClient) -> None:
    resp = anon_client.post("/api/auth/login", json={"username": "nobody", "password": "demo"})
    assert resp.status_code == 400


def test_me_requires_session(anon_client: TestClient) -> None:
    resp = anon_client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"


def test_me_after_login(examiner_client: TestClient) -> None:
    resp = examiner_client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "examiner"


def test_logout_clears_session(examiner_client: TestClient) -> None:
    assert examiner_client.get("/api/me").status_code == 200
    resp = examiner_client.post("/api/auth/logout")
    assert resp.status_code == 204
    assert examiner_client.get("/api/me").status_code == 401


def test_all_three_seeded_roles_can_log_in(
    examiner_client: TestClient, reviewer_client: TestClient, admin_client: TestClient
) -> None:
    assert examiner_client.get("/api/me").json()["role"] == "examiner"
    assert reviewer_client.get("/api/me").json()["role"] == "reviewer"
    assert admin_client.get("/api/me").json()["role"] == "admin"


def test_reviewer_cannot_scan_evidence(reviewer_client: TestClient, evidence_id: str) -> None:
    resp = reviewer_client.post(f"/api/evidence/{evidence_id}/scan", json={})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_examiner_can_scan_evidence(examiner_client: TestClient, evidence_id: str) -> None:
    resp = examiner_client.post(f"/api/evidence/{evidence_id}/scan", json={})
    assert resp.status_code == 202


def test_admin_can_scan_evidence(admin_client: TestClient, evidence_id: str) -> None:
    resp = admin_client.post(f"/api/evidence/{evidence_id}/scan", json={})
    assert resp.status_code == 202
