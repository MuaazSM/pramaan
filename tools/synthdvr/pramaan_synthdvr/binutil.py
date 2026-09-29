"""Small struct-packing helpers shared by every vendor-format writer.

All integers are little-endian unless the caller uses the ``*_be`` variant,
matching docs/01-FORENSIC-CORE.md §4.6 ("All integers little-endian unless
marked BE").
"""

from __future__ import annotations

import struct


def u8(v: int) -> bytes:
    return struct.pack("<B", v & 0xFF)


def u16(v: int) -> bytes:
    return struct.pack("<H", v & 0xFFFF)


def u16_be(v: int) -> bytes:
    return struct.pack(">H", v & 0xFFFF)


def u32(v: int) -> bytes:
    return struct.pack("<I", v & 0xFFFFFFFF)


def u32_be(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def u64(v: int) -> bytes:
    return struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)


def u64_be(v: int) -> bytes:
    return struct.pack(">Q", v & 0xFFFFFFFFFFFFFFFF)


def fixed_str(s: str, size: int) -> bytes:
    """ASCII string, NUL-padded (or truncated) to exactly ``size`` bytes."""
    b = s.encode("ascii")[:size]
    return b + b"\x00" * (size - len(b))


def put(buf: bytearray, offset: int, data: bytes) -> None:
    """Write ``data`` into ``buf`` at ``offset``, growing ``buf`` if needed."""
    end = offset + len(data)
    if end > len(buf):
        buf.extend(b"\x00" * (end - len(buf)))
    buf[offset:end] = data


def crc32(data: bytes) -> int:
    import zlib

    return zlib.crc32(data) & 0xFFFFFFFF
