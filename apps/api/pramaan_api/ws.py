"""``WS /ws?case_id=`` — live job events (docs/02-BACKEND.md §7).

In ``STUB_MODE=1`` (the Wave 0 default), connecting immediately starts a
simulated scan job and pushes a fixed, deterministic sequence of messages
covering every event type in §7: ``job.progress``, ``job.log``,
``evidence.verified``, ``audit.appended``, ``job.done``, and finally one
``job.failed`` message for a second, distinct demo job — so a client only
has to open one connection to see every documented shape, even though a
single job obviously can't both succeed and fail. Real job-driven events
(from ``apps/worker``) replace this once B1 lands the pipeline — callers
only need to know the message shapes, not how they were produced.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pramaan_api.fixtures import store
from pramaan_api.settings import get_settings

router = APIRouter()

# Small, fixed pacing delay between simulated messages — deterministic in
# content, just not instantaneous, so a real client sees a "live" stream.
_STEP_DELAY_S = 0.02


def _simulated_events(case_id: str) -> list[dict[str, Any]]:
    job = next(iter(store.DATA.jobs.values()), None)
    job_id = job.id if job else "job_stub"
    evidence = next(iter(store.DATA.evidence.values()), None)
    events: list[dict[str, Any]] = []
    stages = [
        ("hash_verify", 100.0, "Hashes confirmed"),
        ("fingerprint", 100.0, "hiksim tier A, confidence 0.97"),
        ("carve", 62.0, "Carving unindexed space 1.2/1.9 GiB"),
        ("carve", 100.0, "Carve complete: 41,206 recovered frames"),
        ("timeline", 100.0, "4 clock models built, CH2 OSD +37s"),
    ]
    for stage, pct, message in stages:
        events.append(
            {
                "type": "job.progress",
                "job_id": job_id,
                "stage": stage,
                "pct": pct,
                "throughput_mbps": 612.3,
                "eta_s": max(0, int(100 - pct)),
                "message": message,
            }
        )
        events.append({"type": "job.log", "job_id": job_id, "level": "info", "line": message})

    if evidence is not None:
        events.append(
            {
                "type": "evidence.verified",
                "evidence_id": evidence.id,
                "sha256": evidence.sha256,
                "match": True,
            }
        )

    last_entry = store.DATA.audit_log[-1] if store.DATA.audit_log else None
    if last_entry is not None:
        events.append(
            {
                "type": "audit.appended",
                "seq": last_entry.seq,
                "entry_hash": last_entry.entry_hash,
                "action": last_entry.action,
            }
        )

    summary = {
        "recordings": len(store.DATA.recordings),
        "recovered_frames": 41206,
        "deletions": 1,
    }
    events.append({"type": "job.done", "job_id": job_id, "summary": summary})

    # A second, distinct demo job (docs/02-BACKEND.md §7's job.failed shape)
    # — not the same job as above, which already reported job.done.
    events.append(
        {
            "type": "job.failed",
            "job_id": f"{job_id}_verify_demo",
            "error": {
                "code": "hash_mismatch",
                "message": "Demo: re-hash did not match the registered SHA-256 (illustrative).",
            },
        }
    )
    return events


@router.websocket("/ws")
async def ws_events(websocket: WebSocket, case_id: str | None = None) -> None:
    await websocket.accept()
    settings = get_settings()
    if not settings.stub_mode:
        # Real mode wires this to the worker's event bus; nothing to stream
        # until that lands (B1), so close cleanly rather than hang.
        await websocket.close(code=1000)
        return
    try:
        for event in _simulated_events(case_id or store.DATA.case.id):
            await websocket.send_json(event)
            await asyncio.sleep(_STEP_DELAY_S)
        await websocket.close(code=1000)
    except WebSocketDisconnect:
        return
