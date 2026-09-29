"""``JOB_BACKEND=dramatiq`` (docs/02-BACKEND.md §3): the same ``JobRunner``
interface as ``InlineJobRunner``, backed by a real Dramatiq broker + Redis.

``redis-server`` is installed locally but not always running; callers (the
API, and tests) must call :func:`redis_available` first and skip/fall back
to ``inline`` when it's down — constructing a :class:`DramatiqJobRunner`
without a reachable Redis raises :class:`RedisUnavailable` rather than
hanging.

A single in-process :class:`dramatiq.worker.Worker` thread actually
executes the queued stage messages (there's no separate ``dramatiq``
CLI process in dev/test) — started once per Redis URL and left running for
the life of the process.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import redis as redis_lib

from pramaan_worker.runner import STAGE_NAMES, ProgressCallback, Stage, StageContext, StageResult


class RedisUnavailable(RuntimeError):
    """Raised when ``JOB_BACKEND=dramatiq`` is selected but Redis isn't
    reachable at the configured URL."""


def redis_available(redis_url: str, timeout: float = 0.5) -> bool:
    try:
        client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=timeout)
        return bool(client.ping())
    except Exception:
        return False


_lock = threading.Lock()
_configured_url: str | None = None
_worker: Any = None


def _ensure_worker(redis_url: str) -> None:
    global _configured_url, _worker
    with _lock:
        if _configured_url == redis_url and _worker is not None:
            return
        import dramatiq
        from dramatiq.brokers.redis import RedisBroker
        from dramatiq.results import Results
        from dramatiq.results.backends.redis import RedisBackend
        from dramatiq.worker import Worker

        # dramatiq ships no py.typed marker; not gated by `just check-backend`'s
        # mypy step (that only covers packages/custody, /reporting, /export)
        # but silenced here for a clean bonus `mypy --strict apps/worker` run.
        broker = RedisBroker(url=redis_url)  # type: ignore[no-untyped-call]
        broker.add_middleware(
            Results(backend=RedisBackend(url=redis_url))  # type: ignore[no-untyped-call]
        )
        dramatiq.set_broker(broker)

        # Import (and thus register) the actor only now that the broker is
        # the one we just configured — @dramatiq.actor binds at import
        # time. This process only ever configures one Redis URL, so a
        # plain (non-reloading) import is enough: the second call for the
        # same URL is a no-op (the `_configured_url` check above), and a
        # different URL within one process isn't supported (matches the
        # single-Redis-instance assumption of docs/02-BACKEND.md §3).
        import pramaan_worker.dramatiq_actors  # noqa: F401

        worker = Worker(broker, worker_threads=2)
        worker.start()
        _configured_url = redis_url
        _worker = worker


def _marker_path(ctx: StageContext, stage: str) -> Any:
    return ctx.case_dir / "jobs" / f"{ctx.image_id}.{stage}.done"


class DramatiqJobRunner:
    """Runs each stage as a Dramatiq message on Redis and blocks for its
    result — same resumability contract (marker files) and same
    ``StageResult`` shape as :class:`~pramaan_worker.runner.InlineJobRunner`,
    so both backends can share one test suite (docs/02-BACKEND.md §12:
    "Same results with both job backends").
    """

    def __init__(self, redis_url: str, result_timeout_ms: int = 30_000) -> None:
        if not redis_available(redis_url):
            raise RedisUnavailable(
                f"Redis at {redis_url!r} is not reachable — JOB_BACKEND=dramatiq requires it."
            )
        self._redis_url = redis_url
        self._result_timeout_ms = result_timeout_ms
        _ensure_worker(redis_url)

    def run(
        self,
        stages: dict[str, Stage],
        ctx: StageContext,
        *,
        stage_order: tuple[str, ...] = STAGE_NAMES,
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[StageResult]:
        from pramaan_worker.dramatiq_actors import run_stage_actor

        for stage_name in stage_order:
            if stage_name not in stages:
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
                message = run_stage_actor.send(
                    stage_name,
                    str(ctx.case_dir),
                    ctx.image_id,
                    ctx.input_hash,
                    dict(ctx.options),
                    ctx.evidence_path,
                    ctx.expected_sha256,
                )
                payload = message.get_result(block=True, timeout=self._result_timeout_ms)
                result = StageResult(
                    stage=payload["stage"],
                    ok=payload["ok"],
                    input_hash=payload["input_hash"],
                    output_hash=payload["output_hash"],
                    message=payload["message"],
                    skipped=payload["skipped"],
                )
                if result.ok:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(ctx.input_hash, encoding="utf-8")
            if on_progress is not None:
                on_progress(stage_name, 100.0 if result.ok else 0.0, result.message)
            yield result
            if not result.ok:
                return
