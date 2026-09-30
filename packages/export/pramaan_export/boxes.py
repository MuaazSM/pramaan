"""Minimal ISO base media file format (MP4) box reader/writer, used only to
append and later recover two trailing ``uuid`` boxes on a stream-copied
export MP4: one holding the signed manifest JSON, one holding its detached
Ed25519 signature (docs/02-BACKEND.md §10: "manifest ... embedded in a uuid
box and signed ... detached .sig alongside").

This never touches, re-muxes or re-encodes the video/audio boxes ffmpeg
already wrote (CLAUDE.md rule 3) — it only appends new top-level boxes after
them, which is a standards-legal MP4 structure (players ignore unknown
top-level boxes) and is trivially reversible byte-for-byte.
"""

from __future__ import annotations

import struct
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

#: Two fixed, Pramaan-reserved "extended type" UUIDs distinguishing our two
#: trailing boxes from any other uuid box a tool might add. Generated once
#: and hardcoded (not random per run) so the box tag itself never introduces
#: nondeterminism into the file (CLAUDE.md rule 5).
MANIFEST_BOX_UUID = uuid.UUID("d1eb2ea6-1b3c-4b6e-9d9c-70726d616e00")
SIGNATURE_BOX_UUID = uuid.UUID("d1eb2ea6-1b3c-4b6e-9d9c-70726d616e01")

_BOX_HEADER_LEN = 8  # 4-byte size + 4-byte type
_UUID_EXT_LEN = 16


def _build_uuid_box(tag: uuid.UUID, payload: bytes) -> bytes:
    size = _BOX_HEADER_LEN + _UUID_EXT_LEN + len(payload)
    return struct.pack(">I4s", size, b"uuid") + tag.bytes + payload


def append_uuid_boxes(mp4_bytes: bytes, boxes: list[tuple[uuid.UUID, bytes]]) -> bytes:
    """Append one or more ``uuid`` boxes after ``mp4_bytes`` (already-built,
    valid, stream-copied MP4 bytes), in the given order."""
    out = bytearray(mp4_bytes)
    for tag, payload in boxes:
        out += _build_uuid_box(tag, payload)
    return bytes(out)


@dataclass(frozen=True)
class ParsedBoxes:
    #: Byte offset where the *first* recognised trailing Pramaan uuid box
    #: starts — i.e. the end of the original (ffmpeg-produced) video bytes.
    video_end_offset: int
    manifest: bytes | None
    signature: bytes | None


def _iter_top_level_boxes(data: bytes) -> Iterator[tuple[int, int, bytes]]:
    offset = 0
    n = len(data)
    while offset + _BOX_HEADER_LEN <= n:
        size, box_type = struct.unpack_from(">I4s", data, offset)
        if size == 0:  # box extends to EOF — not produced by our writer
            yield offset, n, box_type
            return
        if size < _BOX_HEADER_LEN or offset + size > n:
            return  # malformed / truncated — stop scanning
        yield offset, offset + size, box_type
        offset += size


def parse_trailing_boxes(data: bytes) -> ParsedBoxes:
    """Recover the manifest/signature payloads this module appended, and the
    offset marking the end of the original video bytes (everything before
    the first Pramaan ``uuid`` box). Tolerant of a file with no such boxes
    (returns ``manifest=None``/``signature=None`` and ``video_end_offset ==
    len(data)``) — the caller decides whether that's a validation failure.
    """
    manifest: bytes | None = None
    signature: bytes | None = None
    video_end = len(data)
    found_any = False
    for start, end, box_type in _iter_top_level_boxes(data):
        if box_type != b"uuid":
            continue
        ext_start = start + _BOX_HEADER_LEN
        payload_start = ext_start + _UUID_EXT_LEN
        if payload_start > end:
            continue
        tag_bytes = data[ext_start:payload_start]
        payload = data[payload_start:end]
        if tag_bytes == MANIFEST_BOX_UUID.bytes:
            manifest = payload
        elif tag_bytes == SIGNATURE_BOX_UUID.bytes:
            signature = payload
        else:
            continue
        found_any = True
        video_end = min(video_end, start)
    if not found_any:
        video_end = len(data)
    return ParsedBoxes(video_end_offset=video_end, manifest=manifest, signature=signature)
