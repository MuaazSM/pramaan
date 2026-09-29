"""Inline vs Dramatiq job-backend parity (docs/02-BACKEND.md §3, §12:
"Same results with both job backends"; "Dramatiq test skipped if Redis
absent").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pramaan_worker.dramatiq_runner import DramatiqJobRunner, redis_available
from pramaan_worker.runner import STAGE_NAMES, InlineJobRunner, StageContext
from pramaan_worker.stages import default_stages

_REDIS_URL = "redis://localhost:6379/0"
_REDIS_UP = redis_available(_REDIS_URL)

pytestmark = pytest.mark.skipif(
    not _REDIS_UP, reason="redis-server is not running at localhost:6379"
)


def _make_image(tmp_path: Path, content: bytes) -> tuple[Path, str]:
    path = tmp_path / "evidence.raw"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def test_inline_and_dramatiq_agree_on_hash_verify(tmp_path: Path) -> None:
    image_path, sha256 = _make_image(tmp_path, b"pramaan test evidence bytes" * 500)
    stage = {"hash_verify": default_stages()["hash_verify"]}

    inline_ctx = StageContext(
        case_dir=tmp_path / "inline",
        image_id="img_parity",
        input_hash="v1",
        evidence_path=str(image_path),
        expected_sha256=sha256,
    )
    inline_result = list(InlineJobRunner().run(stage, inline_ctx, stage_order=("hash_verify",)))[0]

    dramatiq_ctx = StageContext(
        case_dir=tmp_path / "dramatiq",
        image_id="img_parity",
        input_hash="v1",
        evidence_path=str(image_path),
        expected_sha256=sha256,
    )
    runner = DramatiqJobRunner(_REDIS_URL)
    dramatiq_result = list(runner.run(stage, dramatiq_ctx, stage_order=("hash_verify",)))[0]

    assert inline_result.ok == dramatiq_result.ok is True
    assert inline_result.output_hash == dramatiq_result.output_hash == sha256
    assert inline_result.skipped == dramatiq_result.skipped is False


def test_dramatiq_resumability_skips_completed_stage(tmp_path: Path) -> None:
    image_path, sha256 = _make_image(tmp_path, b"resumability bytes" * 200)
    stage = {"hash_verify": default_stages()["hash_verify"]}
    ctx = StageContext(
        case_dir=tmp_path,
        image_id="img_resume",
        input_hash="same-input",
        evidence_path=str(image_path),
        expected_sha256=sha256,
    )
    runner = DramatiqJobRunner(_REDIS_URL)
    first = list(runner.run(stage, ctx, stage_order=("hash_verify",)))[0]
    assert first.skipped is False

    second = list(runner.run(stage, ctx, stage_order=("hash_verify",)))[0]
    assert second.skipped is True


def test_dramatiq_detects_hash_mismatch(tmp_path: Path) -> None:
    image_path, _sha256 = _make_image(tmp_path, b"mismatch bytes" * 100)
    stage = {"hash_verify": default_stages()["hash_verify"]}
    ctx = StageContext(
        case_dir=tmp_path,
        image_id="img_mismatch",
        input_hash="v1",
        evidence_path=str(image_path),
        expected_sha256="0" * 64,
    )
    runner = DramatiqJobRunner(_REDIS_URL)
    result = list(runner.run(stage, ctx, stage_order=("hash_verify",)))[0]
    assert result.ok is False


def test_redis_unavailable_raises_clean_error() -> None:
    from pramaan_worker.dramatiq_runner import RedisUnavailable

    with pytest.raises(RedisUnavailable):
        DramatiqJobRunner("redis://localhost:1/0")


def test_stage_names_constant_unchanged() -> None:
    # Sanity: this test file assumes the Wave 0 stage list is still current.
    assert STAGE_NAMES[0] == "hash_verify"
