"""Canonical JSON serialisation and content-derived ID helpers.

Determinism (CLAUDE.md rule 5): identical logical content must produce
identical bytes, regardless of dict-insertion order, platform, or run.
``canonical_json`` is the single place every other module should go through
before hashing or persisting a JSON-shaped value; ``content_hash`` and
``content_id`` build on it for stable, content-derived identifiers (e.g.
``Recording.id`` = a hash of ``(image_id, channel, start, offset)``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Serialise ``obj`` to canonical UTF-8 JSON bytes.

    Keys are sorted recursively, separators are compact (no whitespace), and
    ``NaN``/``Infinity`` are rejected — the output is safe to hash or write
    to a custody-chain entry.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(obj: Any) -> str:
    """SHA-256 hex digest of ``obj``'s canonical JSON encoding."""
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def content_id(prefix: str, obj: Any, length: int = 16) -> str:
    """Deterministic id: ``f"{prefix}_{content_hash(obj)[:length]}"``.

    Used wherever a model's ``id`` field is defined as "a stable hash of"
    some tuple of its own fields (e.g. ``Recording.id``, ``LogEvent.id``):
    pass those fields as ``obj`` (a dict is the usual choice).
    """
    return f"{prefix}_{content_hash(obj)[:length]}"
