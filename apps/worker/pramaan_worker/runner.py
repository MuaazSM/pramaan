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

from collections.abc import Callable, Iterable, Iterator
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
    # Added by B1 (docs/02-BACKEND.md §6) so `hash_verify` can actually open
    # the evidence image via pramaan_core — optional/defaulted so the Wave 0
    # skeleton's own tests (which don't need real evidence) keep working.
    evidence_path: str | None = None
    expected_sha256: str | None = None


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


def marker_path(ctx: StageContext, stage: str) -> Path:
    """Public accessor for a stage's resumability marker file path (task
    FIX-12). The path depends only on ``ctx.case_dir``/``ctx.image_id``/
    ``stage`` — not on ``ctx.input_hash`` (that's compared against the
    marker's own *contents*, written by :class:`InlineJobRunner`/
    :class:`~pramaan_worker.dramatiq_runner.DramatiqJobRunner`) — so a
    caller that bypasses ``JobRunner.run`` entirely (e.g. the
    confirm-triggered reindex in ``pramaan_api.real.pipeline_store
    ._reindex_confirmed_layout``) can still resolve and invalidate the
    exact marker file an earlier ``JobRunner``-driven ``/scan`` wrote for
    the same stage, regardless of what ``input_hash`` that scan used.
    """
    return _marker_path(ctx, stage)


def invalidate_stage_markers(ctx: StageContext, stage_names: Iterable[str]) -> None:
    """Delete the resumability marker file for each stage in
    ``stage_names``, if present (task FIX-12). For a caller that
    recomputes specific stages directly instead of going through
    ``JobRunner.run`` — the confirm-triggered reindex, specifically — this
    stops any *later* ``JobRunner``-driven run of the same evidence (e.g. a
    ``/scan`` re-run on byte-identical evidence, same ``input_hash``) from
    skipping those stages on the strength of a marker recorded *before*
    the recompute (e.g. from the automatic ``/scan`` that ran while the
    image's layout was still unconfirmed, when ``deletion_verdict`` had an
    empty ``recordings`` table to work from). Safe to call on a stage that
    has no marker yet.
    """
    for stage_name in stage_names:
        marker_path(ctx, stage_name).unlink(missing_ok=True)


def make_runner(backend: str, redis_url: str) -> JobRunner:
    """Factory used by ``apps/api`` (``JOB_BACKEND=inline|dramatiq``,
    docs/02-BACKEND.md §3). Raises ``pramaan_worker.dramatiq_runner
    .RedisUnavailable`` for ``backend="dramatiq"`` when Redis isn't
    reachable — callers should catch this and fall back to ``inline`` (or
    surface a clear error), never hang.
    """
    if backend == "inline":
        return InlineJobRunner()
    if backend == "dramatiq":
        from pramaan_worker.dramatiq_runner import DramatiqJobRunner

        return DramatiqJobRunner(redis_url)
    raise ValueError(f"Unknown job backend: {backend!r}")


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
