"""MPEG-PS pack header / PES packet builders for HIKSIM
(docs/01-FORENSIC-CORE.md §4.6, "Data block" paragraph).

All multi-byte fields here are big-endian (MPEG-PS/PES is a big-endian,
bit-packed format), independent of the module-wide "little-endian unless
marked BE" rule, which applies to the vendor *container* header fields, not
to the embedded standard MPEG-PS/PES structures.
"""

from __future__ import annotations

import struct


def _pack_ts33(marker4: int, ts: int) -> bytes:
    """Pack a 33-bit timestamp (PTS/DTS-style) with the standard 5-byte
    bit layout: marker4(4) ts[32:30](3) '1' ts[29:15](15) '1' ts[14:0](15) '1'.
    """
    ts &= 0x1FFFFFFFF
    b0 = (marker4 << 4) | (((ts >> 30) & 0x7) << 1) | 1
    rem15a = (ts >> 15) & 0x7FFF
    b1 = (rem15a >> 7) & 0xFF
    b2 = ((rem15a & 0x7F) << 1) | 1
    rem15b = ts & 0x7FFF
    b3 = (rem15b >> 7) & 0xFF
    b4 = ((rem15b & 0x7F) << 1) | 1
    return bytes([b0, b1, b2, b3, b4])


def pack_header(scr_90khz: int, mux_rate: int = 5000) -> bytes:
    """14-byte MPEG-PS pack header (ISO/IEC 13818-1), stuffing_length=0.

    ``scr_90khz`` is truncated to 33 bits and used for both the SCR base and
    (with extension=0) SCR extension field, which is sufficient fidelity for
    a synthetic corpus (no real 27 MHz clock to model).
    """
    scr = scr_90khz & 0x1FFFFFFFF
    scr_ext = 0
    bits = 0
    bits |= 0b01 << 78  # 2-bit marker '01'
    bits |= ((scr >> 30) & 0x7) << 75  # scr[32:30]
    bits |= 1 << 74  # marker
    bits |= ((scr >> 15) & 0x7FFF) << 59  # scr[29:15]
    bits |= 1 << 58  # marker
    bits |= (scr & 0x7FFF) << 43  # scr[14:0]
    bits |= 1 << 42  # marker
    bits |= (scr_ext & 0x1FF) << 33  # scr_ext
    bits |= 1 << 32  # marker
    bits |= (mux_rate & 0x3FFFFF) << 10  # program_mux_rate
    bits |= 0b11 << 8  # 2 marker bits
    # reserved(5) + pack_stuffing_length(3) = bits 7..0, left at 0 (no stuffing)
    # 80 bits total -> 10 bytes
    body = bits.to_bytes(10, "big")
    return b"\x00\x00\x01\xba" + body


def video_pes(payload: bytes, pts_90khz: int, stream_id: int = 0xE0) -> bytes:
    """PES packet (start code 00 00 01 E0) with a PTS-only optional header."""
    pts = _pack_ts33(0b0010, pts_90khz)
    header_flags1 = 0b10000000  # '10' marker + no scrambling/priority/alignment/copyright/original
    header_flags2 = 0b10000000  # PTS_DTS_flags = '10' (PTS only)
    header_data_len = len(pts)
    optional = bytes([header_flags1, header_flags2, header_data_len]) + pts
    pes_body = optional + payload
    length = len(pes_body)
    if length > 0xFFFF:
        length = 0  # PES_packet_length may be 0 ("unbounded") for long video payloads
    return b"\x00\x00\x01" + bytes([stream_id]) + struct.pack(">H", length) + pes_body


def private_pes(payload: bytes, stream_id: int = 0xBD) -> bytes:
    """Minimal private_stream_1 PES (00 00 01 BD): start code + stream id +
    length + raw payload, no optional PES header (the vendor's private
    payload — ``HKTS`` + timestamp fields — carries its own structure)."""
    return b"\x00\x00\x01" + bytes([stream_id]) + struct.pack(">H", len(payload)) + payload


def hkts_payload(unix_s: int, ms: int, channel: int) -> bytes:
    return b"HKTS" + struct.pack(">IHB", unix_s & 0xFFFFFFFF, ms & 0xFFFF, channel & 0xFF)
