"""Acceptance test (docs/PROMPTBOOK.md W0.3): the ``/ws?case_id=`` stub emits
every event type in docs/02-BACKEND.md §7.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pramaan_api.fixtures import store

_DOCUMENTED_EVENT_TYPES = {
    "job.progress",
    "job.log",
    "job.done",
    "job.failed",
    "audit.appended",
    "evidence.verified",
}


def test_ws_stub_emits_every_documented_event_type(examiner_client: TestClient) -> None:
    case_id = store.DATA.case.id
    seen_types: list[str] = []
    with examiner_client.websocket_connect(f"/api/ws?case_id={case_id}") as ws:
        while True:
            message = ws.receive_json()
            seen_types.append(message["type"])
            if message["type"] == "job.failed":
                break

    assert seen_types[-1] == "job.failed"
    assert set(seen_types) == _DOCUMENTED_EVENT_TYPES


def test_ws_job_progress_message_shape(examiner_client: TestClient) -> None:
    case_id = store.DATA.case.id
    with examiner_client.websocket_connect(f"/api/ws?case_id={case_id}") as ws:
        message = ws.receive_json()
    assert message["type"] == "job.progress"
    for field in ("job_id", "stage", "pct", "throughput_mbps", "eta_s", "message"):
        assert field in message


def test_ws_audit_appended_and_evidence_verified_present(examiner_client: TestClient) -> None:
    case_id = store.DATA.case.id
    messages = []
    with examiner_client.websocket_connect(f"/api/ws?case_id={case_id}") as ws:
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == "job.done":
                break

    audit_events = [m for m in messages if m["type"] == "audit.appended"]
    assert audit_events and {"seq", "entry_hash", "action"} <= audit_events[0].keys()

    verified_events = [m for m in messages if m["type"] == "evidence.verified"]
    assert verified_events and {"evidence_id", "sha256", "match"} <= verified_events[0].keys()

    done_events = [m for m in messages if m["type"] == "job.done"]
    assert done_events and "summary" in done_events[0]
