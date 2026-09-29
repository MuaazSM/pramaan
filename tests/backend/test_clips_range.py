from __future__ import annotations

from fastapi.testclient import TestClient


def test_clip_stream_without_range_returns_full_body(
    examiner_client: TestClient, clip_id: str
) -> None:
    resp = examiner_client.get(f"/api/clips/{clip_id}/stream")
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    total = int(resp.headers["content-length"])
    assert len(resp.content) == total


def test_clip_stream_range_returns_partial_content(
    examiner_client: TestClient, clip_id: str
) -> None:
    full = examiner_client.get(f"/api/clips/{clip_id}/stream")
    total = int(full.headers["content-length"])

    resp = examiner_client.get(f"/api/clips/{clip_id}/stream", headers={"Range": "bytes=0-15"})
    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 0-15/{total}"
    assert len(resp.content) == 16
    assert resp.content == full.content[:16]


def test_clip_stream_unsatisfiable_range_is_bad_request(
    examiner_client: TestClient, clip_id: str
) -> None:
    resp = examiner_client.get(f"/api/clips/{clip_id}/stream", headers={"Range": "bytes=500-100"})
    assert resp.status_code == 400


def test_clip_stream_missing_clip_is_404(examiner_client: TestClient) -> None:
    resp = examiner_client.get("/api/clips/clip_does_not_exist/stream")
    assert resp.status_code == 404
