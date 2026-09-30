"""DHSIM (Dahua-like, synthetic) VendorParser
(docs/01-FORENSIC-CORE.md §4.5, §4.6 "DHSIM"; packages/formats/specs/dhsim/*.ksy).

Unlike HIKSIM, DHSIM's index entries carry an explicit ``(offset, length)``
for each recording, and a freed (expired) entry keeps its offset/length
intact — so "expiry" deletions are fully recoverable straight from the
index, with no carving needed (docs/01-FORENSIC-CORE.md §4.10, "expiry" vs
"format"). A "format" action instead drops the entry from the live index
entirely (only ``index_entry_count`` slots are ever written back), so a
formatted image's older recordings must be carved from the DHAV byte
stream (``pramaan_recovery.vendor_carve``).
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, ClassVar

from pramaan_core.evidence import EvidenceReader, hash_image
from pramaan_core.ids import content_id
from pramaan_core.ids import frame_id as make_frame_id
from pramaan_core.models import ByteRange, FrameRef, Recording, VendorMatch

from pramaan_formats import dhav
from pramaan_formats.base import register

MAGIC = b"DHFS4.1\x00"
INDEX_ENTRY_SIZE = 32
STATE_ACTIVE = 1
STATE_FREE = 0


class DhsimFormatError(ValueError):
    """Raised when an image doesn't structurally look like DHSIM."""


@dataclass(frozen=True)
class _Header:
    index_offset: int
    index_entry_count: int
    data_offset: int
    data_region_size: int
    init_time_unix_s: int
    model: str | None
    serial: str | None
    log_offset: int
    log_area_size: int


@dataclass(frozen=True)
class _IndexEntry:
    slot: int
    state: int
    channel: int
    start_ts_unix_s: int
    end_ts_unix_s: int
    offset: int
    length: int


def _read_cstr(raw: bytes) -> str | None:
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


@register
class DhsimParser:
    family: ClassVar[str] = "dhsim"

    def __init__(self) -> None:
        self._image_id_cache: dict[str, str] = {}

    # -- header / index reading ---------------------------------------------

    def _read_header(self, r: EvidenceReader) -> _Header:
        if r.size < 0x80 + 48:
            raise DhsimFormatError("image too small for a DHSIM superblock")
        if r.read(0x0, len(MAGIC)) != MAGIC:
            raise DhsimFormatError("DHSIM magic not found at 0x0")
        return _Header(
            index_offset=struct.unpack_from("<Q", r.read(0x10, 8))[0],
            index_entry_count=struct.unpack_from("<I", r.read(0x18, 4))[0],
            data_offset=struct.unpack_from("<Q", r.read(0x20, 8))[0],
            data_region_size=struct.unpack_from("<Q", r.read(0x28, 8))[0],
            init_time_unix_s=struct.unpack_from("<I", r.read(0x30, 4))[0],
            model=_read_cstr(r.read(0x40, 32)),
            serial=_read_cstr(r.read(0x80, 48)),
            log_offset=struct.unpack_from("<Q", r.read(0xC0, 8))[0],
            log_area_size=struct.unpack_from("<Q", r.read(0xC8, 8))[0],
        )

    def _read_index_entries(self, r: EvidenceReader, hdr: _Header) -> list[_IndexEntry]:
        entries = []
        for slot in range(hdr.index_entry_count):
            raw = r.read(hdr.index_offset + slot * INDEX_ENTRY_SIZE, INDEX_ENTRY_SIZE)
            entries.append(
                _IndexEntry(
                    slot=slot,
                    state=raw[0],
                    channel=raw[1],
                    start_ts_unix_s=struct.unpack_from("<I", raw, 4)[0],
                    end_ts_unix_s=struct.unpack_from("<I", raw, 8)[0],
                    offset=struct.unpack_from("<Q", raw, 16)[0],
                    length=struct.unpack_from("<Q", raw, 24)[0],
                )
            )
        return entries

    def _image_id(self, r: EvidenceReader) -> str:
        cached = self._image_id_cache.get(r.path)
        if cached is not None:
            return cached
        sha256, _md5 = hash_image(r)
        image_id = f"img_{sha256[:16]}"
        self._image_id_cache[r.path] = image_id
        return image_id

    # -- VendorParser interface ----------------------------------------------

    def detect(self, r: EvidenceReader) -> VendorMatch | None:
        try:
            hdr = self._read_header(r)
            self._read_index_entries(r, hdr)
        except DhsimFormatError:
            return None
        return VendorMatch(
            family=self.family,
            display_name="Dahua-like (synthetic)",
            platform="dahua",
            tier="A",
            confidence=1.0,
            evidence=[
                f"signature {MAGIC!r} at 0x0",
                f"index parsed at 0x{hdr.index_offset:x} ({hdr.index_entry_count} entries)",
            ],
            model=hdr.model,
            serial=hdr.serial,
            fs_version=None,
        )

    def list_recordings(self, r: EvidenceReader) -> list[Recording]:
        """Only ``state == STATE_ACTIVE`` entries — "live index only" per
        the VendorParser interface (docs/01-FORENSIC-CORE.md §4.5). A freed
        (expired) entry's bytes/offset/length are still fully intact on
        disk, but it is no longer part of the *live* index — it comes back
        from :meth:`unindexed_ranges` instead, exactly like a formatted-away
        recording, so both deletion methods are recovered the same way (by
        the DHAV carver), even though expiry doesn't strictly require
        carving to succeed (the bytes were never touched)."""
        hdr = self._read_header(r)
        entries = self._read_index_entries(r, hdr)
        image_id = self._image_id(r)
        recordings: list[Recording] = []
        for e in entries:
            if e.state != STATE_ACTIVE:
                continue
            rec_id = content_id(
                "rec",
                {
                    "image_id": image_id,
                    "channel": e.channel,
                    "start_ts_us": e.start_ts_unix_s * 1_000_000,
                    "offset": e.offset,
                },
            )
            recordings.append(
                Recording(
                    id=rec_id,
                    image_id=image_id,
                    channel=e.channel,
                    stream="main",
                    start_ts_us=e.start_ts_unix_s * 1_000_000,
                    end_ts_us=e.end_ts_unix_s * 1_000_000,
                    byte_ranges=[ByteRange(offset=e.offset, length=e.length)],
                    source="index",
                    deleted=False,
                )
            )
        return recordings

    def iter_frames(self, r: EvidenceReader, rec: Recording) -> Iterator[FrameRef]:
        byte_range = rec.byte_ranges[0]
        data = r.read(byte_range.offset, byte_range.length)
        records = dhav.walk_dhav_stream(
            data, byte_range.offset, byte_range.offset, byte_range.offset + byte_range.length
        )
        for rec_dhav in records:
            local_start = rec_dhav.payload_offset - byte_range.offset
            payload = data[local_start : local_start + rec_dhav.payload_len]
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            frame_type = rec_dhav.frame_type if rec_dhav.frame_type in ("I", "P") else "other"
            yield FrameRef(
                frame_id=make_frame_id(rec.image_id, rec_dhav.header_offset, payload_sha256),
                image_id=rec.image_id,
                channel=rec_dhav.channel,
                stream=rec.stream,
                codec="h264",
                frame_type=frame_type,  # type: ignore[arg-type]
                header_offset=rec_dhav.header_offset,
                payload_offset=rec_dhav.payload_offset,
                payload_len=rec_dhav.payload_len,
                ts_header_us=rec_dhav.ts_us,
                ts_index_us=None,
                width=None,
                height=None,
                source="index",
                recording_id=rec.id,
                deleted=rec.deleted,
                payload_sha256=payload_sha256,
            )

    def unindexed_ranges(self, r: EvidenceReader) -> list[ByteRange]:
        """Data area minus *active* entries only — a freed (expired) entry's
        bytes are still physically intact (docs/01-FORENSIC-CORE.md
        §4.6/§4.10: expiry frees the index slot but never touches the
        bytes), but since :meth:`list_recordings` treats it as no longer
        "live" (see its docstring), its range comes back here so the DHAV
        carver picks it up — trivially and at ~100% recall, since the
        bytes were never disturbed, unlike a genuinely overwritten format
        scenario."""
        hdr = self._read_header(r)
        entries = self._read_index_entries(r, hdr)
        spans = sorted(
            (e.offset, e.offset + e.length) for e in entries if e.state == STATE_ACTIVE
        )
        total_start = hdr.data_offset
        total_end = min(hdr.data_offset + hdr.data_region_size, r.size)
        ranges: list[ByteRange] = []
        cursor = total_start
        for start, end in spans:
            if start > cursor:
                ranges.append(ByteRange(offset=cursor, length=start - cursor))
            cursor = max(cursor, end)
        if cursor < total_end:
            ranges.append(ByteRange(offset=cursor, length=total_end - cursor))
        return ranges

    def index_state(self, r: EvidenceReader) -> dict[str, Any]:
        hdr = self._read_header(r)
        entries = self._read_index_entries(r, hdr)
        active = [e for e in entries if e.state == STATE_ACTIVE]
        freed = [e for e in entries if e.state == STATE_FREE]
        return {
            "init_time_unix_s": hdr.init_time_unix_s,
            "index_entry_count": hdr.index_entry_count,
            "active_entry_count": len(active),
            "freed_entry_count": len(freed),
            "data_region_size": hdr.data_region_size,
            "log_offset": hdr.log_offset,
            "log_area_size": hdr.log_area_size,
        }
