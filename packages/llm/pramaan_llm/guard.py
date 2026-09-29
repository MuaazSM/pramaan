"""Payload guard (docs/03-AI-TIMELINE.md §8.2, CLAUDE.md rule 6).

``payload_guard`` is the single choke point every payload destined for a
prompt must pass through before it is serialised into a message. It rejects
anything that looks like image/frame/binary data or is simply too large;
only structured metadata (channel numbers, timestamps, counts, verdicts,
short strings) is allowed through. This is a hard safety rule, not a
best-effort filter — callers must not catch and ignore
:class:`PayloadGuardViolation`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pramaan_llm.config import GUARD_MAX_PAYLOAD_BYTES, GUARD_MAX_STRING_LEN

#: Key-name roots that must never appear anywhere in a guarded payload,
#: regardless of their value's shape (docs/03-AI-TIMELINE.md §8.2's literal
#: list, plus the obvious synonyms CLAUDE.md rule 6 implies: no frames,
#: thumbnails, or disk bytes ever reach the model). Matched as a
#: case-insensitive substring against the key with separators stripped, so
#: "frame", "Frame", "frame_bytes", "FrameBytes" and "frame-count" are all
#: caught by one root ("frame") — but generic roots that collide with real
#: metadata field names (``payload_offset``, ``payload_len``, ``clip_id``,
#: ``bytes_recovered``, ...) are deliberately kept as compound-only roots
#: (``payloadbytes``, not ``payload`` or ``bytes`` alone).
_FORBIDDEN_KEY_ROOTS: tuple[str, ...] = (
    "frame",
    "thumb",
    "image",
    "img",
    "pixel",
    "jpeg",
    "jpg",
    "png",
    "bitmap",
    "bmp",
    "video",
    "rawbytes",
    "diskbytes",
    "payloadbytes",
    "clipbytes",
)
_KEY_SEPARATOR_RE = re.compile(r"[_\-\s]")

# Looks-like-encoded-binary heuristics (docs/03-AI-TIMELINE.md §8.2: "rejects
# any string > 256 chars that looks like base64/hex").
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


@dataclass
class PayloadGuardViolation(Exception):
    """Raised by :func:`payload_guard` — the payload is not safe to send."""

    reason: str
    path: str

    def __str__(self) -> str:
        return f"payload guard: {self.reason} at '{self.path}'"


def _check_key(key: str, path: str) -> None:
    normalized = _KEY_SEPARATOR_RE.sub("", key).lower()
    for root in _FORBIDDEN_KEY_ROOTS:
        if root in normalized:
            raise PayloadGuardViolation(f"key name '{key}' looks like binary media", path)


def _check_string(value: str, path: str, *, max_len: int) -> None:
    if len(value) <= max_len:
        return
    candidate = value.strip()
    if _HEX_RE.match(candidate) or _BASE64_RE.match(candidate):
        raise PayloadGuardViolation(
            f"string of length {len(value)} looks like base64/hex-encoded binary", path
        )


def _walk(value: Any, path: str, *, max_len: int) -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise PayloadGuardViolation("raw bytes are not allowed in an LLM payload", path)
    if isinstance(value, str):
        _check_string(value, path, max_len=max_len)
        return
    if isinstance(value, dict):
        for key, sub in value.items():
            key_str = str(key)
            _check_key(key_str, f"{path}.{key_str}")
            _walk(sub, f"{path}.{key_str}", max_len=max_len)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for i, item in enumerate(value):
            _walk(item, f"{path}[{i}]", max_len=max_len)
        return
    # int / float / bool / None / other scalars: always fine.


def payload_guard(
    payload: Any,
    *,
    max_string_len: int = GUARD_MAX_STRING_LEN,
    max_payload_bytes: int = GUARD_MAX_PAYLOAD_BYTES,
) -> None:
    """Raise :class:`PayloadGuardViolation` if ``payload`` is unsafe to send
    to an LLM. Returns ``None`` (no exception) when the payload is only
    structured metadata.

    Checks, in order:

    1. Any ``bytes``/``bytearray``/``memoryview`` anywhere -> rejected.
    2. Any dict key matching a forbidden name (``frame``, ``thumb``,
       ``image``, ``pixels``, ``jpeg``, ...) -> rejected, regardless of the
       value.
    3. Any string longer than ``max_string_len`` that looks like base64 or
       hex -> rejected.
    4. The payload's canonical-JSON size exceeding ``max_payload_bytes`` ->
       rejected (oversize payload).
    """
    _walk(payload, "$", max_len=max_string_len)

    # Oversize check last: cheap for the common case (small dicts), and a
    # payload that already failed 1-3 should report *that* reason first.
    try:
        size = len(json.dumps(payload, default=str).encode("utf-8"))
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise PayloadGuardViolation(f"payload is not JSON-serialisable: {exc}", "$") from exc
    if size > max_payload_bytes:
        raise PayloadGuardViolation(
            f"payload is {size} bytes, over the {max_payload_bytes}-byte cap", "$"
        )
