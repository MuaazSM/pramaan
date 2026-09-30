"""DHSIM ``DHLG`` device-log record parsing
(docs/01-FORENSIC-CORE.md §4.6 "DHSIM" logs, §4.9;
packages/formats/specs/dhsim/dhlg_log.ksy).

32-byte records, "same codes as HIKSIM minor types" per the spec; every
named field sums exactly to 32 bytes (no padding-size ambiguity, unlike
RATS/HIKBTREE — docs/progress/Q1.md "Decisions").
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from pramaan_logs.rats import MINOR_TO_KIND

MAGIC = b"DHLG"
RECORD_SIZE = 32


class MalformedRecord(ValueError):
    """A candidate DHLG record failed structural validation."""


@dataclass(frozen=True)
class DhlgRecord:
    offset: int  # absolute
    ts_unix_s: int
    kind_code: int
    channel: int
    user: str | None
    param: int

    @property
    def kind(self) -> str | None:
        return MINOR_TO_KIND.get(self.kind_code)


def _read_cstr(raw: bytes) -> str | None:
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


def parse_record(data: bytes, base_offset: int, pos: int) -> DhlgRecord:
    """Parse one DHLG record from absolute buffer ``data`` (covering
    ``[base_offset, base_offset + len(data))``) at absolute offset ``pos``."""
    local = pos - base_offset
    if data[local : local + 4] != MAGIC:
        raise MalformedRecord(f"no DHLG magic at {pos}")
    if local + RECORD_SIZE > len(data):
        raise MalformedRecord(f"truncated DHLG record at {pos}")
    body = data[local : local + RECORD_SIZE]
    kind_code = struct.unpack_from("<H", body, 8)[0]
    if kind_code not in MINOR_TO_KIND:
        raise MalformedRecord(f"unrecognised DHLG kind code 0x{kind_code:x} at {pos}")
    ts = struct.unpack_from("<I", body, 4)[0]
    channel = struct.unpack_from("<H", body, 10)[0]
    user = _read_cstr(body[12:28])
    param = struct.unpack_from("<I", body, 28)[0]
    return DhlgRecord(
        offset=pos, ts_unix_s=ts, kind_code=kind_code, channel=channel, user=user, param=param
    )


def walk_log_area(data: bytes, base_offset: int, start: int, end: int) -> list[DhlgRecord]:
    """Sequentially parse fixed-stride DHLG records from absolute ``start``
    to ``end`` (see ``pramaan_logs.rats.walk_log_area``'s docstring — same
    "flat array, skip invalid slots" behaviour)."""
    out: list[DhlgRecord] = []
    pos = start
    while pos + RECORD_SIZE <= end:
        try:
            out.append(parse_record(data, base_offset, pos))
        except MalformedRecord:
            pass
        pos += RECORD_SIZE
    return out
