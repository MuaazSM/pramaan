"""HWSIM (Honeywell-like, synthetic) VendorParser
(docs/01-FORENSIC-CORE.md §4.5, §4.6 "HWSIM";
packages/formats/specs/hwsim/{hwsim_machine_data,hwsim_partition1,hwsim_frame_header}.ksy).

A real, GPT-partitioned disk: protective MBR, primary GPT header + partition
array, vendor "machine data" at sector 34, partition 1 (video) and
partition 2 (system, ``HWSYS`` JSON — not otherwise used by this parser).
Partition 1 carries its own header (data offset / write pointer /
capacity), a block-group index and video block list (informational; both
terminated by an all-zero 16-byte entry, per
``docs/progress/Q2.md`` "Decisions") and a video channel list — the *live*
recording index, one 16-byte entry per recording, also zero-terminated.

Video data is a sequence of individually 20-byte-headered NALs
(docs/01-FORENSIC-CORE.md §4.6: "per NAL, a 20-byte custom header"), grouped
into access units the same way the generic carver does (leading SPS/PPS
NALs attach to the following slice NAL): one :class:`FrameRef` per access
unit, whose ``payload_offset``/``payload_len`` point at that access unit's
own *slice* NAL specifically (matching the synthetic corpus's own
per-access-unit ground-truth convention for this format,
``docs/progress/Q2.md`` "Decisions" — a HWSIM-aware carver/parser walks the
leading SPS/PPS NALs of an access unit separately from its slice NAL, same
as the generic carver's AU grouping does for any format).

Every region size/offset that the spec makes header-relative (GPT partition
extents, ``total_allocatable``, channel-list entry count) is read from the
disk, never hardcoded; the *structural* offsets docs/01-FORENSIC-CORE.md
§4.6 fixes absolutely (sector 34, ``0x40``/``0x40000``/``0x400000``
partition-relative) are literal per the spec, exactly like HIKSIM's/DHSIM's
fixed header offsets.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, ClassVar

from pramaan_core.evidence import EvidenceReader, hash_image
from pramaan_core.ids import content_id
from pramaan_core.models import ByteRange, FrameRef, Recording, VendorMatch

from pramaan_formats.base import register

SECTOR = 512

GPT_SIGNATURE = b"EFI PART"
GPT_HEADER_LBA = 1
MACHINE_DATA_LBA = 34  # docs/01-FORENSIC-CORE.md §4.6: "Machine data at sector 34"
MACHINE_DATA_MAGIC = b"HONEYWELL-NVR-SIM\x00"

PART1_BLOCKGROUP_OFF = 0x40
PART1_BLOCKLIST_OFF = 0x40000
PART1_CHANLIST_OFF = 0x400000
_CHANLIST_MAX_ENTRIES = 4096  # generous cap in case a terminator is ever missing

HW_HDR_SIZE = 20
HW_TYPE_IDR_OR_PARAM = 0x82
HW_TYPE_NON_IDR = 0x02
HW_HDR_FIXED = b"\x80\x01\x00"  # header bytes [1:4], both NAL types
START_CODE = b"\x00\x00\x00\x01"
NAL_SPS = 7
NAL_PPS = 8
NAL_IDR = 5
NAL_NON_IDR = 1
VCL_TYPES = (NAL_IDR, NAL_NON_IDR)


class HwsimFormatError(ValueError):
    """Raised when an image doesn't structurally look like HWSIM."""


@dataclass(frozen=True)
class _GptEntry:
    name: str
    start_lba: int
    end_lba: int


@dataclass(frozen=True)
class _Header:
    part1_start: int  # absolute byte offset of partition 1
    video_data_offset: int  # partition-relative
    next_write_offset: int  # partition-relative
    available_bytes: int
    total_allocatable: int
    model: str | None
    serial: str | None


@dataclass(frozen=True)
class _ChannelEntry:
    slot: int
    channel: int
    stream: int
    start_ts_unix_s: int
    start_offset_4k: int
    length_4k: int


@dataclass(frozen=True)
class _HwNal:
    header_offset: int  # absolute, of this NAL's own 20-byte header
    payload_offset: int  # absolute, of the start code + NAL bytes
    nal_len: int  # includes the 4-byte start code
    ts_us: int
    width: int
    height: int
    nal_type: int  # decoded from the NAL's own header byte (0x1F mask)
    is_vcl: bool


def _read_cstr(raw: bytes) -> str | None:
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


def _read_gpt_entries(r: EvidenceReader, header_lba: int) -> list[_GptEntry]:
    if r.size < (header_lba + 1) * SECTOR:
        raise HwsimFormatError("image too small for a GPT header")
    header = r.read(header_lba * SECTOR, SECTOR)
    if header[0:8] != GPT_SIGNATURE:
        raise HwsimFormatError(f"GPT signature not found at LBA {header_lba}")
    part_entry_lba = struct.unpack_from("<Q", header, 72)[0]
    num_entries = struct.unpack_from("<I", header, 80)[0]
    entry_size = struct.unpack_from("<I", header, 84)[0]
    if entry_size < 56 or not (0 < num_entries <= 16384):
        raise HwsimFormatError("implausible GPT partition array geometry")
    array = r.read(part_entry_lba * SECTOR, num_entries * entry_size)
    entries: list[_GptEntry] = []
    for i in range(num_entries):
        raw = array[i * entry_size : (i + 1) * entry_size]
        if len(raw) < 56:
            break
        start_lba = struct.unpack_from("<Q", raw, 32)[0]
        if start_lba == 0:
            continue
        end_lba = struct.unpack_from("<Q", raw, 40)[0]
        name = raw[56:128].decode("utf-16-le", errors="replace").split("\x00", 1)[0]
        entries.append(_GptEntry(name=name, start_lba=start_lba, end_lba=end_lba))
    return entries


def _find_partition(
    entries: list[_GptEntry], keyword: str, fallback_index: int
) -> _GptEntry | None:
    """Prefer matching by partition name (``keyword`` case-insensitive
    substring, e.g. "VIDEO"); fall back to ``fallback_index``-th by
    ascending start LBA if no name matches (a GPT reader that ignores
    partition names entirely still finds the right partitions this way,
    since the video partition is always written before the system one)."""
    for e in entries:
        if keyword in e.name.upper():
            return e
    ordered = sorted(entries, key=lambda e: e.start_lba)
    if fallback_index < len(ordered):
        return ordered[fallback_index]
    return None


def _read_header(r: EvidenceReader) -> _Header:
    if r.size < (MACHINE_DATA_LBA + 1) * SECTOR:
        raise HwsimFormatError("image too small for a HWSIM GPT disk")
    entries = _read_gpt_entries(r, GPT_HEADER_LBA)
    video = _find_partition(entries, "VIDEO", 0)
    if video is None:
        raise HwsimFormatError("no video partition found in GPT partition array")

    machine_data = r.read(MACHINE_DATA_LBA * SECTOR, SECTOR)
    if machine_data[: len(MACHINE_DATA_MAGIC)] != MACHINE_DATA_MAGIC:
        raise HwsimFormatError(f"HWSIM machine-data magic not found at LBA {MACHINE_DATA_LBA}")
    model = _read_cstr(machine_data[len(MACHINE_DATA_MAGIC) : len(MACHINE_DATA_MAGIC) + 32])
    serial = _read_cstr(
        machine_data[len(MACHINE_DATA_MAGIC) + 32 : len(MACHINE_DATA_MAGIC) + 64]
    )

    part1_start = video.start_lba * SECTOR
    if part1_start + 0x40 > r.size:
        raise HwsimFormatError("image too small for a partition-1 header")
    part1_hdr = r.read(part1_start, 0x40)
    return _Header(
        part1_start=part1_start,
        video_data_offset=struct.unpack_from("<Q", part1_hdr, 0)[0],
        next_write_offset=struct.unpack_from("<Q", part1_hdr, 8)[0],
        available_bytes=struct.unpack_from("<Q", part1_hdr, 16)[0],
        total_allocatable=struct.unpack_from("<Q", part1_hdr, 24)[0],
        model=model,
        serial=serial,
    )


def _read_channel_entries(r: EvidenceReader, hdr: _Header) -> list[_ChannelEntry]:
    base = hdr.part1_start + PART1_CHANLIST_OFF
    entries: list[_ChannelEntry] = []
    for slot in range(_CHANLIST_MAX_ENTRIES):
        raw = r.read(base + slot * 16, 16)
        if len(raw) < 16 or raw == b"\x00" * 16:
            break
        entries.append(
            _ChannelEntry(
                slot=slot,
                channel=raw[0],
                stream=raw[1],
                start_ts_unix_s=struct.unpack_from("<I", raw, 4)[0],
                start_offset_4k=struct.unpack_from("<I", raw, 8)[0],
                length_4k=struct.unpack_from("<I", raw, 12)[0],
            )
        )
    return entries


def walk_hw_nals(data: bytes, base_offset: int, cap: int) -> list[_HwNal]:
    """Walk 20-byte-headered NALs starting at local offset 0 of ``data``
    (covering absolute ``[base_offset, base_offset + cap)``), stopping at
    the all-zero end-of-run sentinel, a header this reader can't validate
    (e.g. the ``0xEE`` tail padding), or ``cap``. Never raises."""
    pos = 0
    out: list[_HwNal] = []
    while pos + HW_HDR_SIZE <= cap:
        header = data[pos : pos + HW_HDR_SIZE]
        if header == b"\x00" * HW_HDR_SIZE:
            break
        type_byte = header[0]
        if type_byte not in (HW_TYPE_IDR_OR_PARAM, HW_TYPE_NON_IDR):
            break
        if header[1:4] != HW_HDR_FIXED:
            break
        width, height = struct.unpack_from("<HH", header, 4)
        nal_len = struct.unpack_from("<I", header, 8)[0]
        ts_us = struct.unpack_from("<Q", header, 12)[0]
        nal_start = pos + HW_HDR_SIZE
        if nal_len < 5 or nal_start + nal_len > cap:
            break
        nal_bytes = data[nal_start : nal_start + nal_len]
        if nal_bytes[0:4] != START_CODE:
            break
        nal_type = nal_bytes[4] & 0x1F
        out.append(
            _HwNal(
                header_offset=base_offset + pos,
                payload_offset=base_offset + nal_start,
                nal_len=nal_len,
                ts_us=ts_us,
                width=width,
                height=height,
                nal_type=nal_type,
                is_vcl=nal_type in VCL_TYPES,
            )
        )
        pos = nal_start + nal_len
    return out


def group_hw_access_units(nals: list[_HwNal]) -> list[list[_HwNal]]:
    """Group a sequential NAL walk into access units: leading non-VCL NALs
    (SPS/PPS) attach to the following slice (VCL) NAL, mirroring
    ``pramaan_recovery.carve.group_access_units`` (docs/01-FORENSIC-CORE.md
    §4.7 step 2). A trailing run with no following VCL NAL is dropped as
    incomplete."""
    aus: list[list[_HwNal]] = []
    cur: list[_HwNal] = []
    for nal in nals:
        cur.append(nal)
        if nal.is_vcl:
            aus.append(cur)
            cur = []
    return aus


def hw_au_to_frame_ref(
    au: list[_HwNal],
    *,
    image_id: str,
    channel: int | None,
    stream: str,
    recording_id: str | None,
    source: str,
    deleted: bool,
) -> FrameRef:
    slice_nal = au[-1]  # group_hw_access_units always ends a group on a VCL NAL
    is_idr = any(n.nal_type == NAL_IDR for n in au)
    return FrameRef(
        frame_id=hashlib.sha256(
            f"{slice_nal.payload_offset}:{slice_nal.nal_len}".encode()
        ).hexdigest()[:24],
        image_id=image_id,
        channel=channel,
        stream=stream,
        codec="h264",
        frame_type="I" if is_idr else "P",
        header_offset=slice_nal.header_offset,
        payload_offset=slice_nal.payload_offset,
        payload_len=slice_nal.nal_len,
        ts_header_us=slice_nal.ts_us,
        ts_index_us=None,
        width=slice_nal.width,
        height=slice_nal.height,
        source=source,  # type: ignore[arg-type]
        recording_id=recording_id,
        deleted=deleted,
    )


def live_channel_roster(r: EvidenceReader) -> list[int]:
    """The distinct live channel numbers, sorted (empty if the image
    doesn't structurally look like HWSIM at all). Used by
    ``pramaan_recovery.vendor_carve.carve_hwsim`` to assign a channel
    number to a carved run that has no channel-list entry of its own — see
    that function's docstring."""
    try:
        hdr = _read_header(r)
        entries = _read_channel_entries(r, hdr)
    except HwsimFormatError:
        return []
    return sorted({e.channel for e in entries})


@register
class HwsimParser:
    family: ClassVar[str] = "hwsim"

    def __init__(self) -> None:
        self._image_id_cache: dict[str, str] = {}

    def _image_id(self, r: EvidenceReader) -> str:
        cached = self._image_id_cache.get(r.path)
        if cached is not None:
            return cached
        sha256, _md5 = hash_image(r)
        image_id = f"img_{sha256[:16]}"
        self._image_id_cache[r.path] = image_id
        return image_id

    # -- VendorParser interface ----------------------------------------

    def detect(self, r: EvidenceReader) -> VendorMatch | None:
        try:
            hdr = _read_header(r)
        except HwsimFormatError:
            return None
        return VendorMatch(
            family=self.family,
            display_name="Honeywell-like (synthetic)",
            platform="honeywell",
            tier="A",
            confidence=1.0,
            evidence=[
                f"GPT signature {GPT_SIGNATURE!r} at LBA {GPT_HEADER_LBA}",
                f"machine-data signature {MACHINE_DATA_MAGIC!r} at LBA {MACHINE_DATA_LBA}",
                f"partition-1 header parsed at 0x{hdr.part1_start:x}",
            ],
            model=hdr.model,
            serial=hdr.serial,
            fs_version=None,
        )

    def list_recordings(self, r: EvidenceReader) -> list[Recording]:
        hdr = _read_header(r)
        entries = _read_channel_entries(r, hdr)
        image_id = self._image_id(r)
        recordings: list[Recording] = []
        for e in entries:
            offset = hdr.part1_start + hdr.video_data_offset + e.start_offset_4k * 4096
            length = e.length_4k * 4096
            start_ts_us = e.start_ts_unix_s * 1_000_000
            end_ts_us = self._recording_end_ts_us(r, offset, length, start_ts_us)
            rec_id = content_id(
                "rec",
                {
                    "image_id": image_id,
                    "channel": e.channel,
                    "start_ts_us": start_ts_us,
                    "offset": offset,
                },
            )
            recordings.append(
                Recording(
                    id=rec_id,
                    image_id=image_id,
                    channel=e.channel,
                    stream="sub" if e.stream != 0 else "main",
                    start_ts_us=start_ts_us,
                    end_ts_us=end_ts_us,
                    byte_ranges=[ByteRange(offset=offset, length=length)],
                    source="index",
                    deleted=False,
                )
            )
        return recordings

    def _recording_end_ts_us(
        self, r: EvidenceReader, offset: int, length: int, fallback: int
    ) -> int:
        data = r.read(offset, length)
        nals = walk_hw_nals(data, offset, length)
        aus = group_hw_access_units(nals)
        if not aus:
            return fallback
        return aus[-1][-1].ts_us

    def iter_frames(self, r: EvidenceReader, rec: Recording) -> Iterator[FrameRef]:
        byte_range = rec.byte_ranges[0]
        data = r.read(byte_range.offset, byte_range.length)
        nals = walk_hw_nals(data, byte_range.offset, byte_range.length)
        for au in group_hw_access_units(nals):
            yield hw_au_to_frame_ref(
                au,
                image_id=rec.image_id,
                channel=rec.channel,
                stream=rec.stream,
                recording_id=rec.id,
                source="index",
                deleted=False,
            )

    def unindexed_ranges(self, r: EvidenceReader) -> list[ByteRange]:
        hdr = _read_header(r)
        entries = _read_channel_entries(r, hdr)
        live_spans = sorted(
            (
                hdr.part1_start + hdr.video_data_offset + e.start_offset_4k * 4096,
                hdr.part1_start
                + hdr.video_data_offset
                + e.start_offset_4k * 4096
                + e.length_4k * 4096,
            )
            for e in entries
        )
        total_start = hdr.part1_start + hdr.video_data_offset
        total_end = min(total_start + hdr.total_allocatable, r.size)
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
        hdr = _read_header(r)
        entries = _read_channel_entries(r, hdr)
        return {
            "video_data_offset": hdr.part1_start + hdr.video_data_offset,
            # `next_write_offset` on disk is already partition-relative
            # (it embeds `video_data_offset` itself — see the writer's
            # `PART1_DATA_OFF + next_write_offset_local`), so it is *not*
            # added to `video_data_offset` again here.
            "next_write_offset": hdr.part1_start + hdr.next_write_offset,
            "available_bytes": hdr.available_bytes,
            "total_allocatable": hdr.total_allocatable,
            "live_channel_entry_count": len(entries),
        }
