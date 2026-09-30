"""DHAV frame record parsing (docs/01-FORENSIC-CORE.md §4.6 "DHSIM";
packages/formats/specs/dhsim/dhav_record.ksy).

Self-describing frame records (header checksum + footer length-echo) let a
DHAV stream be walked either from a known index offset (the live-index
parser) or discovered anywhere a candidate ``DHAV`` magic is found (the
vendor carver, ``pramaan_recovery.vendor_carve``) — both use this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

HEADER_SIZE = 24
FOOTER_SIZE = 8
TYPE_I = 0xFD
TYPE_P = 0xFC
TYPE_AUDIO = 0xF0

FRAME_TYPE_BY_CODE: dict[int, str] = {TYPE_I: "I", TYPE_P: "P", TYPE_AUDIO: "other"}


class MalformedRecord(ValueError):
    """A candidate DHAV record failed header-checksum or footer validation."""


@dataclass(frozen=True)
class DhavRecord:
    header_offset: int  # absolute
    total_length: int
    channel: int
    frame_type: str  # "I" | "P" | "other"
    sequence: int
    ts_us: int
    payload_offset: int  # absolute
    payload_len: int
    end_offset: int  # absolute, just past this record's footer


def _unpack_datetime(packed: int) -> datetime:
    sec = packed & 0x3F
    minute = (packed >> 6) & 0x3F
    hour = (packed >> 12) & 0x1F
    day = (packed >> 17) & 0x1F
    month = (packed >> 22) & 0xF
    year = 2000 + ((packed >> 26) & 0x3F)
    return datetime(year, month, day, hour, minute, sec, tzinfo=UTC)


def parse_record(data: bytes, base_offset: int, pos: int) -> DhavRecord:
    """Parse one DHAV record from absolute buffer ``data`` (covering
    ``[base_offset, base_offset + len(data))``) at absolute offset ``pos``."""
    local = pos - base_offset
    if data[local : local + 4] != b"DHAV":
        raise MalformedRecord(f"no DHAV magic at {pos}")
    if local + HEADER_SIZE > len(data):
        raise MalformedRecord(f"truncated DHAV header at {pos}")
    header = data[local : local + HEADER_SIZE]
    type_byte = header[4]
    frame_type = FRAME_TYPE_BY_CODE.get(type_byte)
    if frame_type is None:
        raise MalformedRecord(f"unrecognised DHAV frame type 0x{type_byte:02x} at {pos}")
    channel = header[6]
    sequence = int.from_bytes(header[8:12], "little")
    total_length = int.from_bytes(header[12:16], "little")
    packed_dt = int.from_bytes(header[16:20], "little")
    ms = int.from_bytes(header[20:22], "little")
    checksum = header[23]
    if (sum(header[0:23]) & 0xFF) != checksum:
        raise MalformedRecord(f"checksum mismatch at {pos}")
    if total_length < HEADER_SIZE + FOOTER_SIZE:
        raise MalformedRecord(f"implausible total_length at {pos}")
    if local + total_length > len(data):
        raise MalformedRecord(f"record runs past buffer end at {pos}")
    footer_local = local + total_length - FOOTER_SIZE
    footer = data[footer_local : footer_local + FOOTER_SIZE]
    if footer[0:4] != b"dhav":
        raise MalformedRecord(f"footer magic mismatch at {pos}")
    if int.from_bytes(footer[4:8], "little") != total_length:
        raise MalformedRecord(f"footer length mismatch at {pos}")
    try:
        dt = _unpack_datetime(packed_dt)
    except ValueError as exc:
        raise MalformedRecord(f"invalid packed datetime at {pos}") from exc
    ts_us = int(dt.timestamp()) * 1_000_000 + ms * 1000
    payload_len = total_length - HEADER_SIZE - FOOTER_SIZE
    return DhavRecord(
        header_offset=pos,
        total_length=total_length,
        channel=channel,
        frame_type=frame_type,
        sequence=sequence,
        ts_us=ts_us,
        payload_offset=pos + HEADER_SIZE,
        payload_len=payload_len,
        end_offset=pos + total_length,
    )


def walk_dhav_stream(data: bytes, base_offset: int, start: int, end: int) -> list[DhavRecord]:
    """Sequentially parse consecutive DHAV records from absolute ``start``
    to ``end``; stops at the first record that fails validation."""
    pos = start
    out: list[DhavRecord] = []
    while pos < end:
        try:
            rec = parse_record(data, base_offset, pos)
        except MalformedRecord:
            break
        out.append(rec)
        pos = rec.end_offset
    return out
