"""HIKSIM (Hikvision-like, synthetic) VendorParser
(docs/01-FORENSIC-CORE.md §4.5, §4.6 "HIKSIM"; packages/formats/specs/hiksim/*.ksy).

Reads the fixed-offset header, the HIKBTREE recording index and, for each
live recording, walks its MPEG-PS elementary stream
(``pramaan_formats.mpegps``) to yield one :class:`FrameRef` per access
unit. Every region size (block size, block count, entry count, log area
size) is read from the header/index, never hardcoded
(docs/01-FORENSIC-CORE.md §4.6).
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

from pramaan_formats import mpegps, nalutil
from pramaan_formats.base import register

MAGIC = b"HIKVISION@HANGZHOU"
MAGIC_OFFSET = 0x210
HIKBTREE_ENTRY_STRIDE = 48
HIKBTREE_ENTRIES_START = 0x60
IMKH_HEADER_SIZE = 40
STATE_IN_USE = 0


class HiksimFormatError(ValueError):
    """Raised when an image doesn't structurally look like HIKSIM."""


@dataclass(frozen=True)
class _Header:
    disk_capacity_bytes: int
    hikbtree_offset: int
    hikbtree_size: int
    data_offset: int
    data_block_size: int
    data_block_count: int
    log_offset: int
    log_area_size: int
    init_time_unix_s: int
    model: str | None
    serial: str | None


@dataclass(frozen=True)
class _HikbtreeEntry:
    slot: int
    state: int
    channel: int
    has_footage: int
    start_ts_unix_s: int
    end_ts_unix_s: int
    data_block_offset: int

    @property
    def in_use(self) -> bool:
        return self.state == STATE_IN_USE


def _read_cstr(raw: bytes) -> str | None:
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


@register
class HiksimParser:
    family: ClassVar[str] = "hiksim"

    def __init__(self) -> None:
        self._image_id_cache: dict[str, str] = {}

    # -- header / index reading -------------------------------------------------

    def _read_header(self, r: EvidenceReader) -> _Header:
        if r.size < 0x320 + 48:
            raise HiksimFormatError("image too small for a HIKSIM header")
        if r.read(MAGIC_OFFSET, len(MAGIC)) != MAGIC:
            raise HiksimFormatError(f"HIKSIM magic not found at 0x{MAGIC_OFFSET:x}")
        return _Header(
            disk_capacity_bytes=struct.unpack_from("<Q", r.read(0x230, 8))[0],
            hikbtree_offset=struct.unpack_from("<Q", r.read(0x240, 8))[0],
            hikbtree_size=struct.unpack_from("<Q", r.read(0x248, 8))[0],
            data_offset=struct.unpack_from("<Q", r.read(0x250, 8))[0],
            data_block_size=struct.unpack_from("<Q", r.read(0x258, 8))[0],
            data_block_count=struct.unpack_from("<I", r.read(0x260, 4))[0],
            log_offset=struct.unpack_from("<Q", r.read(0x270, 8))[0],
            log_area_size=struct.unpack_from("<Q", r.read(0x278, 8))[0],
            init_time_unix_s=struct.unpack_from("<I", r.read(0x280, 4))[0],
            model=_read_cstr(r.read(0x300, 32)),
            serial=_read_cstr(r.read(0x320, 48)),
        )

    def _read_hikbtree_entries(self, r: EvidenceReader, hdr: _Header) -> list[_HikbtreeEntry]:
        if r.read(hdr.hikbtree_offset, 8) != b"HIKBTREE":
            raise HiksimFormatError("HIKBTREE magic not found")
        entry_count = struct.unpack_from(
            "<I", r.read(hdr.hikbtree_offset + 0x10, 4)
        )[0]
        base = hdr.hikbtree_offset + HIKBTREE_ENTRIES_START
        entries = []
        for slot in range(entry_count):
            raw = r.read(base + slot * HIKBTREE_ENTRY_STRIDE, HIKBTREE_ENTRY_STRIDE)
            entries.append(
                _HikbtreeEntry(
                    slot=slot,
                    state=struct.unpack_from("<Q", raw, 0)[0],
                    channel=raw[8],
                    has_footage=raw[9],
                    start_ts_unix_s=struct.unpack_from("<I", raw, 16)[0],
                    end_ts_unix_s=struct.unpack_from("<I", raw, 20)[0],
                    data_block_offset=struct.unpack_from("<Q", raw, 24)[0],
                )
            )
        return entries

    def _block_ps_extent(self, r: EvidenceReader, hdr: _Header, block_off: int) -> int:
        """The real end offset of a block's written MPEG-PS content
        (docs/01-FORENSIC-CORE.md §4.6: "Unused block tail is zero-filled")."""
        cap = min(hdr.data_block_size, max(0, r.size - block_off))
        if cap <= IMKH_HEADER_SIZE:
            return block_off + min(cap, IMKH_HEADER_SIZE)
        data = r.read(block_off, cap)
        aus = mpegps.walk_ps_stream(
            data, block_off, block_off + IMKH_HEADER_SIZE, block_off + cap
        )
        if not aus:
            return block_off + IMKH_HEADER_SIZE
        return aus[-1].end_offset

    def _image_id(self, r: EvidenceReader) -> str:
        cached = self._image_id_cache.get(r.path)
        if cached is not None:
            return cached
        sha256, _md5 = hash_image(r)
        image_id = f"img_{sha256[:16]}"
        self._image_id_cache[r.path] = image_id
        return image_id

    # -- VendorParser interface ---------------------------------------------

    def detect(self, r: EvidenceReader) -> VendorMatch | None:
        try:
            hdr = self._read_header(r)
            self._read_hikbtree_entries(r, hdr)
        except HiksimFormatError:
            return None
        return VendorMatch(
            family=self.family,
            display_name="Hikvision-like (synthetic)",
            platform="hikvision",
            tier="A",
            confidence=1.0,
            evidence=[
                f"signature {MAGIC!r} at 0x{MAGIC_OFFSET:x}",
                f"HIKBTREE index parsed at 0x{hdr.hikbtree_offset:x}",
            ],
            model=hdr.model,
            serial=hdr.serial,
            fs_version=None,
        )

    def list_recordings(self, r: EvidenceReader) -> list[Recording]:
        hdr = self._read_header(r)
        entries = self._read_hikbtree_entries(r, hdr)
        image_id = self._image_id(r)
        recordings: list[Recording] = []
        for e in entries:
            if not e.in_use:
                continue
            end_offset = self._block_ps_extent(r, hdr, e.data_block_offset)
            length = end_offset - e.data_block_offset
            rec_id = content_id(
                "rec",
                {
                    "image_id": image_id,
                    "channel": e.channel,
                    "start_ts_us": e.start_ts_unix_s * 1_000_000,
                    "offset": e.data_block_offset,
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
                    byte_ranges=[ByteRange(offset=e.data_block_offset, length=length)],
                    source="index",
                    deleted=False,
                )
            )
        return recordings

    def iter_frames(self, r: EvidenceReader, rec: Recording) -> Iterator[FrameRef]:
        byte_range = rec.byte_ranges[0]
        data = r.read(byte_range.offset, byte_range.length)
        aus = mpegps.walk_ps_stream(
            data,
            byte_range.offset,
            byte_range.offset + IMKH_HEADER_SIZE,
            byte_range.offset + byte_range.length,
        )
        for au in aus:
            local_start = au.payload_offset - byte_range.offset
            payload = data[local_start : local_start + au.payload_len]
            frame_type = nalutil.classify_access_unit(payload)
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            yield FrameRef(
                frame_id=make_frame_id(rec.image_id, au.header_offset, payload_sha256),
                image_id=rec.image_id,
                channel=au.channel if au.channel is not None else rec.channel,
                stream=rec.stream,
                codec="h264",
                frame_type=frame_type,  # type: ignore[arg-type]
                header_offset=au.header_offset,
                payload_offset=au.payload_offset,
                payload_len=au.payload_len,
                ts_header_us=au.ts_header_us,
                ts_index_us=None,
                width=None,
                height=None,
                source="index",
                recording_id=rec.id,
                deleted=False,
                payload_sha256=payload_sha256,
            )

    def unindexed_ranges(self, r: EvidenceReader) -> list[ByteRange]:
        hdr = self._read_header(r)
        entries = self._read_hikbtree_entries(r, hdr)
        live_spans: list[tuple[int, int]] = []
        for e in entries:
            if not e.in_use:
                continue
            end = self._block_ps_extent(r, hdr, e.data_block_offset)
            live_spans.append((e.data_block_offset, end))
        live_spans.sort()

        total_start = hdr.data_offset
        total_end = min(
            hdr.data_offset + hdr.data_block_count * hdr.data_block_size, r.size
        )
        ranges: list[ByteRange] = []
        cursor = total_start
        for start, end in live_spans:
            if start > cursor:
                ranges.append(ByteRange(offset=cursor, length=start - cursor))
            cursor = max(cursor, end)
        if cursor < total_end:
            ranges.append(ByteRange(offset=cursor, length=total_end - cursor))
        return ranges

    def index_state(self, r: EvidenceReader) -> dict[str, Any]:
        hdr = self._read_header(r)
        entries = self._read_hikbtree_entries(r, hdr)
        live = [e for e in entries if e.in_use]
        return {
            "init_time_unix_s": hdr.init_time_unix_s,
            "disk_capacity_bytes": hdr.disk_capacity_bytes,
            "data_block_count": hdr.data_block_count,
            "data_block_size": hdr.data_block_size,
            "hikbtree_entry_count": len(entries),
            "live_entry_count": len(live),
            "log_offset": hdr.log_offset,
            "log_area_size": hdr.log_area_size,
        }
