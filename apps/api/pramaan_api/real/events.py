"""In-process WS event bus for real-mode jobs (docs/02-BACKEND.md §7).

A plain per-case list, appended to synchronously from whatever thread runs
a job (FastAPI's sync routes run in a thread pool) and polled by the WS
endpoint's coroutine. ``list.append``/slicing are atomic under the GIL, so
no extra lock is needed for this simple bounded producer/many-poller
pattern — good enough for one demo process, not a distributed event bus.
"""

from __future__ import annotations

from typing import Any

_MAX_EVENTS_PER_CASE = 1000
_events: dict[str, list[dict[str, Any]]] = {}


def publish(case_id: str, event: dict[str, Any]) -> None:
    bucket = _events.setdefault(case_id, [])
    bucket.append(event)
    if len(bucket) > _MAX_EVENTS_PER_CASE:
        del bucket[: len(bucket) - _MAX_EVENTS_PER_CASE]


def events_since(case_id: str, offset: int) -> tuple[list[dict[str, Any]], int]:
    bucket = _events.get(case_id, [])
    return bucket[offset:], len(bucket)


def reset_for_tests(case_id: str | None = None) -> None:
    if case_id is None:
        _events.clear()
    else:
        _events.pop(case_id, None)
