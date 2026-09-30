"""``parse_logs(reader, family) -> list[LogEvent]``
(docs/01-FORENSIC-CORE.md §4.9): HIKSIM (``RATS``) and DHSIM (``DHLG``)
device-log parsers, plus carving log records found outside the declared
log area (they survive a "format" action, which never touches the log
region in this corpus, but a real device could relocate/shrink it).

Deduplicates by ``offset`` — a record found both by the declared-area walk
and by the whole-image carve (the common case here, since the log area
*is* still part of the image) is only reported once, keyed on the
declared-area copy when both exist.
"""

from __future__ import annotations

import struct
from typing import Any

from pramaan_core import scan
from pramaan_core.evidence import EvidenceReader, hash_image
from pramaan_core.ids import content_id
from pramaan_core.models import LogEvent

from pramaan_logs import dhlg, rats

_HIKSIM_MAGIC = b"HIKVISION@HANGZHOU"
_HIKSIM_MAGIC_OFFSET = 0x210
_HIKSIM_LOG_OFFSET_FIELD = 0x270
_HIKSIM_LOG_SIZE_FIELD = 0x278

_DHSIM_MAGIC = b"DHFS4.1\x00"
_DHSIM_LOG_OFFSET_FIELD = 0xC0
_DHSIM_LOG_SIZE_FIELD = 0xC8


def _image_id(r: EvidenceReader) -> str:
    sha256, _md5 = hash_image(r)
    return f"img_{sha256[:16]}"


def _read_u64(r: EvidenceReader, offset: int) -> int:
    value: int = struct.unpack("<Q", r.read(offset, 8))[0]
    return value


def parse_logs(reader: EvidenceReader, family: str) -> list[LogEvent]:
    """The B2 integration-contract entry point
    (docs/progress/B2.md "Integration contract"). Returns an empty list for
    any family with no documented log backend (HWSIM, XSIM, GENSIM,
    ``"unknown"``) — never raises."""
    if family == "hiksim":
        return _parse_hiksim(reader)
    if family == "dhsim":
        return _parse_dhsim(reader)
    return []


def _parse_hiksim(reader: EvidenceReader) -> list[LogEvent]:
    if reader.size < _HIKSIM_MAGIC_OFFSET + len(_HIKSIM_MAGIC):
        return []
    if reader.read(_HIKSIM_MAGIC_OFFSET, len(_HIKSIM_MAGIC)) != _HIKSIM_MAGIC:
        return []
    if reader.size < _HIKSIM_LOG_SIZE_FIELD + 8:
        return []
    log_offset = _read_u64(reader, _HIKSIM_LOG_OFFSET_FIELD)
    log_area_size = _read_u64(reader, _HIKSIM_LOG_SIZE_FIELD)
    log_end = min(log_offset + log_area_size, reader.size)

    records: dict[int, rats.RatsRecord] = {}
    if log_offset < log_end:
        data = reader.read(log_offset, log_end - log_offset)
        for rec in rats.walk_log_area(data, log_offset, log_offset, log_end):
            records[rec.offset] = rec
    for rec in _carve_rats(reader, log_offset, log_end):
        records.setdefault(rec.offset, rec)

    image_id = _image_id(reader)
    return [
        _rats_to_event(rec, image_id)
        for rec in sorted(records.values(), key=lambda r: r.offset)
        if rec.kind is not None
    ]


def _carve_rats(
    reader: EvidenceReader, exclude_start: int, exclude_end: int
) -> list[rats.RatsRecord]:
    hits = scan.scan_signatures(reader.path, [rats.MAGIC], 0, reader.size)
    out: list[rats.RatsRecord] = []
    consumed: list[tuple[int, int]] = []
    for _pattern_idx, offset in hits:
        if exclude_start <= offset < exclude_end:
            continue
        if any(s <= offset < e for s, e in consumed):
            continue
        if offset + rats.RECORD_SIZE > reader.size:
            continue
        data = reader.read(offset, rats.RECORD_SIZE)
        try:
            rec = rats.parse_record(data, offset, offset)
        except rats.MalformedRecord:
            continue
        consumed.append((offset, offset + rats.RECORD_SIZE))
        out.append(rec)
    return out


def _rats_to_event(rec: rats.RatsRecord, image_id: str) -> LogEvent:
    kind = rec.kind
    assert kind is not None
    details: dict[str, Any] = {}
    if kind == "time_change":
        details = {"old_ts_us": rec.param1 * 1_000_000, "new_ts_us": rec.param2 * 1_000_000}
    elif kind in ("playback", "export"):
        details = {
            "range_start_ts_us": rec.param1 * 1_000_000,
            "range_end_ts_us": rec.param2 * 1_000_000,
        }
    return LogEvent(
        id=content_id("log", {"image_id": image_id, "offset": rec.offset, "kind": kind}),
        image_id=image_id,
        ts_device_us=rec.ts_unix_s * 1_000_000,
        kind=kind,  # type: ignore[arg-type]
        user=rec.user,
        channel=rec.channel or None,
        details=details,
        offset=rec.offset,
    )


def _parse_dhsim(reader: EvidenceReader) -> list[LogEvent]:
    if reader.size < len(_DHSIM_MAGIC):
        return []
    if reader.read(0x0, len(_DHSIM_MAGIC)) != _DHSIM_MAGIC:
        return []
    if reader.size < _DHSIM_LOG_SIZE_FIELD + 8:
        return []
    log_offset = _read_u64(reader, _DHSIM_LOG_OFFSET_FIELD)
    log_area_size = _read_u64(reader, _DHSIM_LOG_SIZE_FIELD)
    log_end = min(log_offset + log_area_size, reader.size)

    records: dict[int, dhlg.DhlgRecord] = {}
    if log_offset < log_end:
        data = reader.read(log_offset, log_end - log_offset)
        for rec in dhlg.walk_log_area(data, log_offset, log_offset, log_end):
            records[rec.offset] = rec
    for rec in _carve_dhlg(reader, log_offset, log_end):
        records.setdefault(rec.offset, rec)

    image_id = _image_id(reader)
    return [
        _dhlg_to_event(rec, image_id)
        for rec in sorted(records.values(), key=lambda r: r.offset)
        if rec.kind is not None
    ]


def _carve_dhlg(
    reader: EvidenceReader, exclude_start: int, exclude_end: int
) -> list[dhlg.DhlgRecord]:
    hits = scan.scan_signatures(reader.path, [dhlg.MAGIC], 0, reader.size)
    out: list[dhlg.DhlgRecord] = []
    consumed: list[tuple[int, int]] = []
    for _pattern_idx, offset in hits:
        if exclude_start <= offset < exclude_end:
            continue
        if any(s <= offset < e for s, e in consumed):
            continue
        if offset + dhlg.RECORD_SIZE > reader.size:
            continue
        data = reader.read(offset, dhlg.RECORD_SIZE)
        try:
            rec = dhlg.parse_record(data, offset, offset)
        except dhlg.MalformedRecord:
            continue
        consumed.append((offset, offset + dhlg.RECORD_SIZE))
        out.append(rec)
    return out


def _dhlg_to_event(rec: dhlg.DhlgRecord, image_id: str) -> LogEvent:
    kind = rec.kind
    assert kind is not None
    details: dict[str, Any] = {}
    if kind in ("playback", "export"):
        # DHLG carries one u32 `param` (unlike RATS's param1/param2 pair);
        # the writer uses it as the referenced recording's start time.
        details = {"range_start_ts_us": rec.param * 1_000_000}
    # DHLG's single `param` field can't carry a (old_ts, new_ts) pair the
    # way RATS's time_change does, and this corpus never emits a DHSIM
    # time_change record to observe the real convention against — left
    # empty rather than guessed (CLAUDE.md: never fabricate).
    return LogEvent(
        id=content_id("log", {"image_id": image_id, "offset": rec.offset, "kind": kind}),
        image_id=image_id,
        ts_device_us=rec.ts_unix_s * 1_000_000,
        kind=kind,  # type: ignore[arg-type]
        user=rec.user,
        channel=rec.channel or None,
        details=details,
        offset=rec.offset,
    )
