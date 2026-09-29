"""WS events from real jobs (docs/02-BACKEND.md §7, task B1).

A verify/scan job publishes its progress/log/evidence.verified/audit/done
events synchronously (docs/02-BACKEND.md §12's pipeline runs inline by
default) before the HTTP response returns, so connecting to the WS
afterwards drains that backlog immediately — no timing race to manage.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _intake_body() -> dict[str, str]:
    return {
        "seized_at_local": "2026-03-12T16:40:00+05:30",
        "dvr_displayed_time": "2026-03-12T16:45:12",
        "reference_time": "2026-03-12T16:40:00+05:30",
        "reference_source": "NTP phone clock",
        "timezone": "Asia/Kolkata",
    }


def test_ws_streams_real_job_events(real_client: TestClient, real_evidence_dir: Path) -> None:
    case = real_client.post(
        "/api/cases", json={"case_number": "CR-WS-0001", "title": "WS test"}
    ).json()
    file_path = real_evidence_dir / "ws.raw"
    file_path.write_bytes(b"ws test bytes" * 1000)
    image = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "x", "intake": _intake_body()},
    ).json()

    job_resp = real_client.post(f"/api/evidence/{image['id']}/verify")
    assert job_resp.status_code == 202

    with real_client.websocket_connect(f"/api/ws?case_id={case['id']}") as ws:
        types_seen = []
        while True:
            message = ws.receive_json()
            types_seen.append(message["type"])
            if message["type"] in ("job.done", "job.failed"):
                break

    assert "job.progress" in types_seen
    assert "evidence.verified" in types_seen
    assert "audit.appended" in types_seen
    assert types_seen[-1] == "job.done"
