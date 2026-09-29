"""Job runner interface (docs/02-BACKEND.md §6) — Wave 0 skeleton.

The real scan pipeline (``apps/worker`` proper) lands in a later BACKEND
task. This module fixes the *shape* every stage and every backend
(``inline`` today, ``dramatiq`` in Docker Compose — docs/02-BACKEND.md §3)
must agree on, so W0.3's API can already type its job responses
(``pramaan_api.schemas.Job``/``JobStage``) against something real.

Each stage is a pure function ``stage(ctx) -> StageResult`` that is
idempotent and resumable: ``InlineJobRunner`` skips a stage whose
``output_marker`` already exists with the same input hash, per
docs/02-BACKEND.md §6 ("skips when its output exists with matching input
hash").
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# The 11 stages in order (docs/02-BACKEND.md §6). Real implementations live
# in packages/core, packages/formats, packages/recovery, packages/logs,
# packages/timeline, packages/analytics — this module only fixes the names
# and order.
STAGE_NAMES: tuple[str, ...] = (
    "hash_verify",
    "fingerprint",
    "parse_index",
    "infer_layout",
    "carve",
    "frame_index",
    "logs",
    "deletion_verdict",
    "clips",
    "timeline",
    "motion",
)

# Overall-progress weights (docs/02-BACKEND.md §6: "carve 35%, infer 10%,
# clips 15%, timeline 15%, others share the rest").
_WEIGHTED = {"carve": 0.35, "infer_layout": 0.10, "clips": 0.15, "timeline": 0.15}
_UNWEIGHTED_SHARE = (1.0 - sum(_WEIGHTED.values())) / (len(STAGE_NAMES) - len(_WEIGHTED))
STAGE_WEIGHTS: dict[str, float] = {
    name: _WEIGHTED.get(name, _UNWEIGHTED_SHARE) for name in STAGE_NAMES
}


@dataclass(frozen=True)
class StageResult:
    stage: str
    ok: bool
    input_hash: str
    output_hash: str | None
    message: str
    skipped: bool = False


@dataclass
class StageContext:
    """Everything a stage function needs. Real fields (case dir, evidence
    reader, DB connection, ...) are added by the task that implements the
    real pipeline; this skeleton only carries what's needed to demonstrate
    idempotent/resumable dispatch.
    """

    case_dir: Path
    image_id: str
    input_hash: str
    options: dict[str, object] = field(default_factory=dict)


class Stage(Protocol):
    def __call__(self, ctx: StageContext) -> StageResult: ...


ProgressCallback = Callable[[str, float, str], None]
"""``(stage, pct, message) -> None`` — matches the ``job.progress`` WS event
fields ``stage``/``pct``/``message`` (docs/02-BACKEND.md §7)."""


class JobRunner(Protocol):
    """Both ``inline`` and ``dramatiq`` job backends (docs/02-BACKEND.md §3)
    implement this interface, so they're interchangeable and must pass the
    same tests.
    """

    def run(
        self,
        stages: dict[str, Stage],
        ctx: StageContext,
        *,
        stage_order: tuple[str, ...] = STAGE_NAMES,
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[StageResult]: ...


def _marker_path(ctx: StageContext, stage: str) -> Path:
    return ctx.case_dir / "jobs" / f"{ctx.image_id}.{stage}.done"


class InlineJobRunner:
    """Runs stages sequentially in-process (``JOB_BACKEND=inline``, the
    dev/demo default — docs/02-BACKEND.md §3). A stage is skipped if its
    marker file already records the same ``input_hash`` (resumability).
    """

    def run(
        self,
        stages: dict[str, Stage],
        ctx: StageContext,
        *,
        stage_order: tuple[str, ...] = STAGE_NAMES,
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[StageResult]:
        for stage_name in stage_order:
            stage = stages.get(stage_name)
            if stage is None:
                continue
            marker = _marker_path(ctx, stage_name)
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == ctx.input_hash:
                result = StageResult(
                    stage=stage_name,
                    ok=True,
                    input_hash=ctx.input_hash,
                    output_hash=None,
                    message=f"{stage_name}: skipped (already done for this input)",
                    skipped=True,
                )
            else:
                if on_progress is not None:
                    on_progress(stage_name, 0.0, f"{stage_name}: starting")
                result = stage(ctx)
                if result.ok:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(ctx.input_hash, encoding="utf-8")
            if on_progress is not None:
                on_progress(stage_name, 100.0 if result.ok else 0.0, result.message)
            yield result
            if not result.ok:
                return
