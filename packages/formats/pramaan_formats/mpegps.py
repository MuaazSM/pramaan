"""Low-level MPEG-PS / PES structural parsing for HIKSIM data blocks
(docs/01-FORENSIC-CORE.md §4.6 "Data block";
packages/formats/specs/hiksim/hiksim_data_block.ksy).

Big-endian per ISO/IEC 13818-1, independent of the HIKSIM container's
little-endian convention. Operates on plain ``bytes`` buffers (already read
from an :class:`~pramaan_core.evidence.EvidenceReader`, never opens files
itself) so it is equally usable by the live index parser
(``pramaan_formats.hiksim``) and the vendor carver
(``pramaan_recovery.vendor_carve``).
"""

from __future__ import annotations

from dataclasses import dataclass

PACK_START = b"\x00\x00\x01\xba"
VIDEO_PES_START = b"\x00\x00\x01\xe0"
PRIVATE_PES_START = b"\x00\x00\x01\xbd"
HKTS_MAGIC = b"HKTS"

PACK_HEADER_LEN = 14


class MalformedStream(ValueError):
    """A structural PS/PES record failed to parse at a given local offset."""


@dataclass(frozen=True)
class PackHeader:
    local_offset: int
    length: int  # always PACK_HEADER_LEN
    pts90: int  # 33-bit SCR, reused as a 90 kHz PTS-style per-frame clock


@dataclass(frozen=True)
class PrivateRecord:
    local_offset: int
    length: int  # start code + stream id + length field + payload
    payload: bytes


@dataclass(frozen=True)
class VideoRecord:
    local_offset: int
    length: int  # total packet length
    payload_local_offset: int
    payload_len: int


@dataclass(frozen=True)
class HktsPayload:
    unix_s: int
    ms: int
    channel: int

    @property
    def time_us(self) -> int:
        return self.unix_s * 1_000_000 + self.ms * 1000


def parse_pack_header(data: bytes, pos: int) -> PackHeader:
    if data[pos : pos + 4] != PACK_START:
        raise MalformedStream(f"no pack start code at {pos}")
    body = data[pos + 4 : pos + PACK_HEADER_LEN]
    if len(body) != 10:
        raise MalformedStream(f"truncated pack header at {pos}")
    bits = int.from_bytes(body, "big")
    scr = (
        (((bits >> 75) & 0x7) << 30)
        | (((bits >> 59) & 0x7FFF) << 15)
        | ((bits >> 43) & 0x7FFF)
    )
    return PackHeader(local_offset=pos, length=PACK_HEADER_LEN, pts90=scr & 0x1FFFFFFFF)


def parse_private_pes(data: bytes, pos: int) -> PrivateRecord:
    if data[pos : pos + 4] != PRIVATE_PES_START:
        raise MalformedStream(f"no private PES start code at {pos}")
    if pos + 6 > len(data):
        raise MalformedStream(f"truncated private PES header at {pos}")
    length = int.from_bytes(data[pos + 4 : pos + 6], "big")
    payload = data[pos + 6 : pos + 6 + length]
    if len(payload) != length:
        raise MalformedStream(f"truncated private PES payload at {pos}")
    return PrivateRecord(local_offset=pos, length=6 + length, payload=bytes(payload))


def parse_hkts(payload: bytes) -> HktsPayload | None:
    """Decode ``payload`` as an HKTS record, or ``None`` if it isn't one."""
    if len(payload) != 11 or payload[:4] != HKTS_MAGIC:
        return None
    unix_s = int.from_bytes(payload[4:8], "big")
    ms = int.from_bytes(payload[8:10], "big")
    channel = payload[10]
    return HktsPayload(unix_s=unix_s, ms=ms, channel=channel)


def parse_video_pes(data: bytes, pos: int) -> VideoRecord:
    if data[pos : pos + 4] != VIDEO_PES_START:
        raise MalformedStream(f"no video PES start code at {pos}")
    if pos + 6 > len(data):
        raise MalformedStream(f"truncated video PES header at {pos}")
    length = int.from_bytes(data[pos + 4 : pos + 6], "big")
    if length == 0:
        # "Unbounded" PES length (payload > 0xFFFF bytes) — not produced by
        # the synthetic corpus (docs/01-FORENSIC-CORE.md §4.6); a real
        # implementation would need to scan forward for the next start
        # code. Treated as malformed here so callers stop cleanly rather
        # than guessing at a boundary.
        raise MalformedStream(f"unbounded video PES length at {pos} not supported")
    header_start = pos + 6
    if header_start + 3 > len(data):
        raise MalformedStream(f"truncated video PES optional header at {pos}")
    header_data_len = data[header_start + 2]
    payload_local_offset = header_start + 3 + header_data_len
    payload_len = length - 3 - header_data_len
    if payload_len < 0:
        raise MalformedStream(f"inconsistent video PES length at {pos}")
    total_len = 6 + length
    if pos + total_len > len(data):
        raise MalformedStream(f"video PES payload runs past buffer end at {pos}")
    return VideoRecord(
        local_offset=pos,
        length=total_len,
        payload_local_offset=payload_local_offset,
        payload_len=payload_len,
    )


@dataclass(frozen=True)
class AccessUnit:
    """One access unit recovered from a HIKSIM MPEG-PS stream."""

    header_offset: int  # absolute offset of the pack header
    payload_offset: int  # absolute offset of the AU's Annex B bytes
    payload_len: int
    end_offset: int  # absolute offset just past this AU's video PES packet
    pts90: int
    ts_header_us: int | None  # absolute device-clock time, if derivable
    channel: int | None  # from the nearest preceding HKTS anchor


@dataclass(frozen=True)
class _RawAu:
    header_offset: int
    payload_offset: int
    payload_len: int
    end_offset: int
    pts90: int
    direct_time_us: int | None  # only set on the AU an HKTS record directly precedes
    direct_channel: int | None


def walk_ps_stream(data: bytes, base_offset: int, start: int, end: int) -> list[AccessUnit]:
    """Sequentially parse consecutive PS records in ``data`` (a buffer
    covering absolute ``[base_offset, base_offset + len(data))``) from
    absolute position ``start`` up to ``end``.

    Stops at the first byte sequence that isn't a recognised pack header —
    typically the block's zero-filled tail, but also wherever a carved
    fragment's sequential structure has been disrupted (e.g. by a partial
    overwrite). Never raises: any parse failure simply ends the walk with
    whatever access units were found before it.

    Every access unit's pack header carries a 90 kHz PTS-style counter
    (``pts90``, wraps at 2**33); only the access unit immediately preceded
    by an HKTS private PES carries an *absolute* clock reading directly.
    Every other access unit's ``ts_header_us``/``channel`` are derived from
    the *nearest* HKTS anchor found anywhere in this walk (forward from a
    preceding one, or backward from the first one found — e.g. a carved
    fragment that starts mid-GOP, before the block's first keyframe) via
    modular arithmetic on ``pts90``. A fragment with no HKTS anchor at all
    gets ``ts_header_us=None``/``channel=None`` throughout.
    """
    pos = start
    raw: list[_RawAu] = []
    while pos < end:
        local = pos - base_offset
        try:
            pack = parse_pack_header(data, local)
        except MalformedStream:
            break
        pending_pts90 = pack.pts90
        header_offset = pos
        cursor_local = local + pack.length

        direct_channel: int | None = None
        direct_time: int | None = None
        if data[cursor_local : cursor_local + 4] == PRIVATE_PES_START:
            try:
                priv = parse_private_pes(data, cursor_local)
            except MalformedStream:
                break
            hkts = parse_hkts(priv.payload)
            if hkts is not None:
                direct_time = hkts.time_us
                direct_channel = hkts.channel
            cursor_local += priv.length

        try:
            vid = parse_video_pes(data, cursor_local)
        except MalformedStream:
            break

        end_local = cursor_local + vid.length
        raw.append(
            _RawAu(
                header_offset=header_offset,
                payload_offset=base_offset + vid.payload_local_offset,
                payload_len=vid.payload_len,
                end_offset=base_offset + end_local,
                pts90=pending_pts90,
                direct_time_us=direct_time,
                direct_channel=direct_channel,
            )
        )
        pos = base_offset + end_local

    return _resolve_timestamps(raw)


def _resolve_timestamps(raw: list[_RawAu]) -> list[AccessUnit]:
    """Fill in ``ts_header_us``/``channel`` from the nearest HKTS anchor
    (preceding one preferred; the first one found in the walk is used
    backward for any leading access units before it)."""
    aus: list[AccessUnit] = []
    anchor: tuple[int, int, int] | None = None  # (anchor_pts90, anchor_time_us, channel)
    first_anchor: tuple[int, int, int] | None = None
    pending: list[_RawAu] = []

    def _delta_us(from_pts90: int, to_pts90: int) -> int:
        delta90 = (to_pts90 - from_pts90) & 0x1FFFFFFFF
        return round(delta90 * 1_000_000 / 90_000)

    for item in raw:
        if item.direct_time_us is not None:
            anchor = (item.pts90, item.direct_time_us, item.direct_channel)  # type: ignore[assignment]
            if first_anchor is None:
                first_anchor = anchor
            assert first_anchor is not None
            a_pts90, a_time, a_channel = first_anchor
            for held in pending:
                # Backward-fill using the *first* anchor ever found, for any
                # access units that came before it.
                ts = a_time - _delta_us(held.pts90, a_pts90)
                aus.append(_finish(held, ts, a_channel))
            pending = []
            aus.append(_finish(item, item.direct_time_us, item.direct_channel))
            continue

        if anchor is not None:
            a_pts90, a_time, a_channel = anchor
            ts = a_time + _delta_us(a_pts90, item.pts90)
            aus.append(_finish(item, ts, a_channel))
        else:
            pending.append(item)

    for held in pending:
        # No anchor ever appeared in this walk at all.
        aus.append(_finish(held, None, None))
    return aus


def _finish(item: _RawAu, ts_header_us: int | None, channel: int | None) -> AccessUnit:
    return AccessUnit(
        header_offset=item.header_offset,
        payload_offset=item.payload_offset,
        payload_len=item.payload_len,
        end_offset=item.end_offset,
        pts90=item.pts90,
        ts_header_us=ts_header_us,
        channel=channel,
    )
