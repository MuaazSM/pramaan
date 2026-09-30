"""HIKSIM ``RATS`` device-log record parsing
(docs/01-FORENSIC-CORE.md §4.6 "HIKSIM" logs, §4.9;
packages/formats/specs/hiksim/rats_log.ksy).

64-byte records, read at their literal field offsets (per
``docs/progress/Q1.md`` "Decisions": the trailing pad field is the one
that's enlarged to hit the documented 64-byte stride, every *named* field
keeps the offset the spec's field order implies).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"RATS"
RECORD_SIZE = 64

#: RATS ``minor`` type -> LogEvent.kind (docs/01-FORENSIC-CORE.md §4.6).
MINOR_TO_KIND: dict[int, str] = {
    0x01: "login",
    0x02: "logout",
    0x10: "playback",
    0x11: "export",
    0x40: "hdd_format",
    0x41: "time_change",
    0x50: "power_on",
}


class MalformedRecord(ValueError):
    """A candidate RATS record failed structural validation."""


@dataclass(frozen=True)
class RatsRecord:
    offset: int  # absolute
    ts_unix_s: int
    major: int
    minor: int
    user: str | None
    channel: int
    param1: int
    param2: int

    @property
    def kind(self) -> str | None:
        return MINOR_TO_KIND.get(self.minor)


def _read_cstr(raw: bytes) -> str | None:
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


def parse_record(data: bytes, base_offset: int, pos: int) -> RatsRecord:
    """Parse one RATS record from absolute buffer ``data`` (covering
    ``[base_offset, base_offset + len(data))``) at absolute offset ``pos``."""
    local = pos - base_offset
    if data[local : local + 4] != MAGIC:
        raise MalformedRecord(f"no RATS magic at {pos}")
    if local + RECORD_SIZE > len(data):
        raise MalformedRecord(f"truncated RATS record at {pos}")
    body = data[local : local + RECORD_SIZE]
    minor = struct.unpack_from("<H", body, 10)[0]
    if minor not in MINOR_TO_KIND:
        raise MalformedRecord(f"unrecognised RATS minor type 0x{minor:x} at {pos}")
    ts = struct.unpack_from("<I", body, 4)[0]
    major = struct.unpack_from("<H", body, 8)[0]
    user = _read_cstr(body[12:28])
    channel = struct.unpack_from("<I", body, 28)[0]
    param1 = struct.unpack_from("<Q", body, 32)[0]
    param2 = struct.unpack_from("<Q", body, 40)[0]
    return RatsRecord(
        offset=pos,
        ts_unix_s=ts,
        major=major,
        minor=minor,
        user=user,
        channel=channel,
        param1=param1,
        param2=param2,
    )


def walk_log_area(data: bytes, base_offset: int, start: int, end: int) -> list[RatsRecord]:
    """Sequentially parse fixed-stride RATS records from absolute ``start``
    to ``end``. Unlike a carving walk, this never "stops at the first
    failure" — a freed/never-written slot (all zero) is simply skipped, so
    later live slots are still found (log areas are a flat array, not a
    self-terminating stream)."""
    out: list[RatsRecord] = []
    pos = start
    while pos + RECORD_SIZE <= end:
        try:
            out.append(parse_record(data, base_offset, pos))
        except MalformedRecord:
            pass
        pos += RECORD_SIZE
    return out
