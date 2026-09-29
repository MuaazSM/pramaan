from __future__ import annotations

from fastapi.testclient import TestClient


def test_verify_accepts_multipart_file_with_intact_prefix(examiner_client: TestClient) -> None:
    content = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64
    files = {"file": ("export-1.mp4", content, "video/mp4")}
    resp = examiner_client.post("/api/exports/verify", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["signature_valid"] is True
    assert body["source_matches_registered_evidence"] is True


def test_verify_rejects_garbage_file(examiner_client: TestClient) -> None:
    files = {"file": ("garbage.bin", b"not an mp4", "application/octet-stream")}
    resp = examiner_client.post("/api/exports/verify", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["signature_valid"] is False
