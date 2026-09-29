"""Stage bodies (docs/02-BACKEND.md §6).

B1 owns the job-runner machinery and stage 1 (``hash_verify``, which reads
real evidence bytes through ``pramaan_core.evidence.EvidenceReader`` — the
only reader CLAUDE.md rule 2 allows). Stages 2-11 (``fingerprint`` through
``motion``) belong to later tasks (C2/B2/A2 — parsers, carving, timeline,
motion) that don't exist yet; ``default_stages()`` registers a placeholder
for each of them so a real ``scan`` job can still run the whole pipeline
shape end-to-end (and exercise ``JobRunner``/WS wiring) without fabricating
forensic findings. A placeholder always succeeds and says so in its
message; nothing it "produces" is persisted or reported as a finding.
"""

from __future__ import annotations

from pramaan_core.evidence import EvidenceReader, hash_image

from pramaan_worker.runner import STAGE_NAMES, Stage, StageContext, StageResult


def hash_verify(ctx: StageContext) -> StageResult:
    """Re-hash the evidence image and compare against the hash recorded at
    registration time (``ctx.expected_sha256``), if given.
    """
    if not ctx.evidence_path:
        raise ValueError("hash_verify requires StageContext.evidence_path")
    reader = EvidenceReader.open(ctx.evidence_path)
    try:
        sha256, _md5 = hash_image(reader)
    finally:
        reader.close()

    if ctx.expected_sha256 is not None and sha256 != ctx.expected_sha256:
        return StageResult(
            stage="hash_verify",
            ok=False,
            input_hash=ctx.input_hash,
            output_hash=sha256,
            message=(
                f"hash mismatch: expected sha256={ctx.expected_sha256}, recomputed sha256={sha256}"
            ),
        )
    return StageResult(
        stage="hash_verify",
        ok=True,
        input_hash=ctx.input_hash,
        output_hash=sha256,
        message=f"sha256={sha256} confirmed",
    )


def _make_placeholder(name: str) -> Stage:
    def _run(ctx: StageContext) -> StageResult:
        return StageResult(
            stage=name,
            ok=True,
            input_hash=ctx.input_hash,
            output_hash=None,
            message=f"{name}: placeholder — real implementation lands in a later BACKEND/AI task",
        )

    return _run


_PLACEHOLDER_STAGES: dict[str, Stage] = {
    name: _make_placeholder(name) for name in STAGE_NAMES if name != "hash_verify"
}


def default_stages() -> dict[str, Stage]:
    """Every stage name mapped to a real implementation (``hash_verify``)
    or a placeholder (everything else). Callers that only want a subset
    (e.g. ``/evidence/{eid}/verify`` → just ``hash_verify``) filter this
    dict by stage name before calling ``JobRunner.run``.
    """
    return {"hash_verify": hash_verify, **_PLACEHOLDER_STAGES}
