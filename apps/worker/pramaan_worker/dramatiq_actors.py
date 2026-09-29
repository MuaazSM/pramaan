"""The one Dramatiq actor this task registers.

A real stage function is an arbitrary Python closure (``StageContext ->
StageResult``), which can't cross a process boundary — so the actor doesn't
receive one. Instead it receives a stage *name* and looks it up in
``pramaan_worker.stages.default_stages()`` on the worker side, which is
exactly the set of stages B1 ships (see ``stages.py``). This module must be
imported only *after* a broker has been configured
(``pramaan_worker.dramatiq_runner`` does this) — ``@dramatiq.actor`` binds
to whatever broker is current at import/decoration time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import dramatiq

from pramaan_worker.runner import StageContext
from pramaan_worker.stages import default_stages


@dramatiq.actor(store_results=True, max_retries=0, time_limit=120_000)
def run_stage_actor(
    stage_name: str,
    case_dir: str,
    image_id: str,
    input_hash: str,
    options: dict[str, object],
    evidence_path: str | None,
    expected_sha256: str | None,
) -> dict[str, Any]:
    ctx = StageContext(
        case_dir=Path(case_dir),
        image_id=image_id,
        input_hash=input_hash,
        options=options,
        evidence_path=evidence_path,
        expected_sha256=expected_sha256,
    )
    stage = default_stages()[stage_name]
    result = stage(ctx)
    return {
        "stage": result.stage,
        "ok": result.ok,
        "input_hash": result.input_hash,
        "output_hash": result.output_hash,
        "message": result.message,
        "skipped": result.skipped,
    }
