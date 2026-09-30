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


def frame_id(image_id: str, offset: int, payload_sha256: str, length: int = 24) -> str:
    """Deterministic id for one *physical* frame (FIX-3).

    Must be unique per physical frame, not per payload. Hashing only the
    payload bytes (the pre-FIX-3 scheme) collapses distinct frames that
    happen to carry identical bytes — e.g. repeated/carved duplicates or a
    static scene — into a single id, which silently merges unrelated rows
    anywhere a caller keys a dict by ``frame_id`` (docs/progress/QD.md).
    Mixing in ``image_id`` and the frame's own byte offset (its
    ``header_offset`` when the format has one, else ``payload_offset``)
    makes two frames at different physical locations always get different
    ids, while re-deriving the id for the *same* physical frame (same
    image, same offset, same bytes) is stable across runs and hosts
    (CLAUDE.md rule 5). ``payload_sha256`` (the full hex digest, kept
    verbatim on ``FrameRef.payload_sha256``) is still part of the input so
    a frame whose bytes are found to differ on re-read also gets a
    different id.
    """
    return content_id(
        "frm",
        {"image_id": image_id, "offset": offset, "payload_sha256": payload_sha256},
        length=length,
    )
