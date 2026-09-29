"""Cursor pagination helper (docs/02-BACKEND.md §4: ``?cursor=&limit=``).

The cursor is an opaque string; this stub implementation encodes it as a
plain base-10 offset into an already-sorted list, which is enough for the
in-memory fixtures. A real DB-backed implementation would encode a
(sort_key, id) pair instead — callers outside this module never need to
know the encoding.
"""

from __future__ import annotations

from typing import TypeVar

from pramaan_api.errors import bad_request

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def paginate(items: list[T], cursor: str | None, limit: int | None) -> tuple[list[T], str | None]:
    offset = _decode_cursor(cursor)
    page_size = _clamp_limit(limit)
    page = items[offset : offset + page_size]
    next_offset = offset + page_size
    next_cursor = str(next_offset) if next_offset < len(items) else None
    return page, next_cursor


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise bad_request(f"Invalid cursor '{cursor}'.") from exc
    if offset < 0:
        raise bad_request(f"Invalid cursor '{cursor}'.")
    return offset


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit <= 0:
        raise bad_request("limit must be positive.")
    return min(limit, MAX_LIMIT)
