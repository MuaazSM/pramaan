"""Smoke test for the Wave 0 job-runner interface skeleton
(``apps/worker/pramaan_worker/runner.py`` — docs/02-BACKEND.md §6).
"""

from __future__ import annotations

from pathlib import Path

from pramaan_worker.runner import (
    STAGE_NAMES,
    STAGE_WEIGHTS,
    InlineJobRunner,
    StageContext,
    StageResult,
)


def _ok_stage(ctx: StageContext) -> StageResult:
    return StageResult(
        stage="hash_verify",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash="deadbeef",
        message="hash_verify: ok",
    )


def test_stage_weights_sum_to_one() -> None:
    assert abs(sum(STAGE_WEIGHTS.values()) - 1.0) < 1e-9
    assert set(STAGE_WEIGHTS) == set(STAGE_NAMES)


def test_inline_runner_runs_and_records_marker(tmp_path: Path) -> None:
    ctx = StageContext(case_dir=tmp_path, image_id="img_test", input_hash="hash_v1")
    runner = InlineJobRunner()
    results = list(runner.run({"hash_verify": _ok_stage}, ctx, stage_order=("hash_verify",)))
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].skipped is False
    marker = tmp_path / "jobs" / "img_test.hash_verify.done"
    assert marker.read_text(encoding="utf-8") == "hash_v1"


def test_inline_runner_skips_completed_stage_with_same_input_hash(tmp_path: Path) -> None:
    ctx = StageContext(case_dir=tmp_path, image_id="img_test", input_hash="hash_v1")
    runner = InlineJobRunner()
    list(runner.run({"hash_verify": _ok_stage}, ctx, stage_order=("hash_verify",)))

    calls = []

    def _counting_stage(c: StageContext) -> StageResult:
        calls.append(1)
        return _ok_stage(c)

    results = list(
        runner.run({"hash_verify": _counting_stage}, ctx, stage_order=("hash_verify",))
    )
    assert results[0].skipped is True
    assert calls == []  # stage function never re-invoked — resumability


def test_inline_runner_reruns_when_input_hash_changes(tmp_path: Path) -> None:
    ctx_v1 = StageContext(case_dir=tmp_path, image_id="img_test", input_hash="hash_v1")
    runner = InlineJobRunner()
    list(runner.run({"hash_verify": _ok_stage}, ctx_v1, stage_order=("hash_verify",)))

    ctx_v2 = StageContext(case_dir=tmp_path, image_id="img_test", input_hash="hash_v2")
    results = list(runner.run({"hash_verify": _ok_stage}, ctx_v2, stage_order=("hash_verify",)))
    assert results[0].skipped is False
