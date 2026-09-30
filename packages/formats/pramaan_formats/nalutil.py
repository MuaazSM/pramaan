"""Minimal H.264 Annex B NAL splitting, shared by the HIKSIM and DHSIM
parsers to classify an access unit as "I" or "P" without decoding.

Full SPS field extraction (width/height/profile) lives in
``pramaan_recovery.sps`` — the generic carver's job (docs/01-FORENSIC-CORE.md
§4.7); this module only answers "is there an IDR NAL in this payload?" and
"is there an SPS NAL, and if so, where does it start?", which is all a
vendor parser needs to fill ``FrameRef.frame_type``.
"""

from __future__ import annotations

NAL_SEI = 6
NAL_SPS = 7
NAL_PPS = 8
NAL_IDR = 5
NAL_NON_IDR = 1


def find_nals(payload: bytes) -> list[tuple[int, bytes]]:
    """Split ``payload`` (one Annex B access unit) into ``(nal_type, nal_bytes)``
    pairs, ``nal_bytes`` excluding the start code. Handles 3- and 4-byte
    start codes (mirrors ``tools/synthdvr/pramaan_synthdvr/video.py``'s
    ``find_nals``, the writer's own algorithm, byte for byte)."""
    i = 0
    n = len(payload)
    marks: list[tuple[int, int]] = []
    while i < n - 2:
        if payload[i] == 0 and payload[i + 1] == 0 and payload[i + 2] == 1:
            sc_start = i - 1 if (i > 0 and payload[i - 1] == 0) else i
            marks.append((sc_start, i + 3))
            i += 3
        else:
            i += 1
    out: list[tuple[int, bytes]] = []
    for idx, (_sc_start, nal_start) in enumerate(marks):
        nal_end = marks[idx + 1][0] if idx + 1 < len(marks) else n
        if nal_start >= n:
            continue
        nal_type = payload[nal_start] & 0x1F
        out.append((nal_type, payload[nal_start:nal_end]))
    return out


def classify_access_unit(payload: bytes) -> str:
    """"I" if ``payload`` contains an IDR slice NAL, else "P"."""
    for nal_type, _ in find_nals(payload):
        if nal_type == NAL_IDR:
            return "I"
    return "P"


def first_sps(payload: bytes) -> bytes | None:
    """The RBSP bytes (NAL header stripped) of the first SPS NAL in
    ``payload``, or ``None``."""
    for nal_type, nal_bytes in find_nals(payload):
        if nal_type == NAL_SPS and len(nal_bytes) > 1:
            return nal_bytes[1:]
    return None
