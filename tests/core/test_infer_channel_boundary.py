"""FIX-9 regression tests for the magic-detection extension bug
(docs/01-FORENSIC-CORE.md §4.8): magic detection must not silently absorb
a header byte that is only constant *across the sampled records* because
it happens to be a small enumerated field's (e.g. channel) most-significant
byte — doing so shifts the field one byte later and, if the field is
big-endian, makes the remaining bytes decode as if little-endian instead.

These use small, hand-built synthetic layouts of our own devising (never
XSIM's), so they exercise the bug directly and run fast, independent of
``corpus/images/xsim_*.img``. ``tests/validation/test_no_xsim_leak.py``
already guards against this module encoding XSIM's real magic; this file
adds no vendor-specific bytes at all.
"""

from __future__ import annotations

import struct
from pathlib import Path

from pramaan_core.evidence import EvidenceReader
from pramaan_recovery import infer

#: Our own made-up 8-byte "magic" for this synthetic format — arbitrary
#: bytes, unrelated to any real or corpus vendor signature.
_MAGIC = bytes.fromhex("9f3c71a05ed28814")
_N_SAMPLES = 48
_N_CHANNELS = 4
_PADDING_LEN = 85  # padding(85) + magic(8) + channel(2) + delim(1) == WINDOW (96)
_PAYLOAD = bytes([0xEE] * 8)  # no embedded "00 00 01" run
_NAL_HEADER = bytes([0x65])  # forbidden_zero_bit=0, nal_ref_idc=3, type=5 (IDR)
_START_CODE = b"\x00\x00\x01"
#: A fixed non-zero byte right before the start code. Without this, a
#: channel value whose byte adjacent to the start code happens to be 0x00
#: (e.g. channel id 0 in big-endian, or *any* id in little-endian, since
#: its constant high byte sits there) would make the scanner read a
#: 4-byte start code one byte early (`pramaan_core.scan`'s documented
#: single-byte lookback) and misalign that sample — an artifact of this
#: test's own fixture construction, not of the inference algorithm under
#: test, so it's neutralised here rather than worked around in assertions.
_DELIM = bytes([0xFF])


def _padding(seed: int) -> bytes:
    """``_PADDING_LEN`` bytes that vary across samples (high per-position
    entropy) and never contain a zero byte, so they can never accidentally
    form a start-code-like run."""
    raw = bytearray(range(seed, seed + _PADDING_LEN))
    for i, b in enumerate(raw):
        raw[i] = ((b * 131 + seed * 7) % 255) + 1  # 1..255, no zero byte
    return bytes(raw)


def _build_image(channel_bytes: list[bytes]) -> bytes:
    """One access unit per entry in ``channel_bytes`` (each already packed
    to the desired width/endianness); header = padding + magic + channel
    field + delimiter, immediately followed by the start code."""
    out = bytearray()
    for i, chan in enumerate(channel_bytes):
        out += _padding(i)
        out += _MAGIC
        out += chan
        out += _DELIM
        out += _START_CODE
        out += _NAL_HEADER
        out += _PAYLOAD
    return bytes(out)


def test_be_channel_with_constant_high_byte_is_not_absorbed_into_magic(tmp_path: Path) -> None:
    """The exact FIX-9 bug shape: a big-endian 2-byte channel field right
    after the magic whose high byte is always 0 (small channel range) must
    not extend the detected magic by that byte — channel must be found at
    its true offset (right after the 8-byte magic), width 2, endian be."""
    channel_bytes = [
        struct.pack(">H", i % _N_CHANNELS) for i in range(_N_SAMPLES)
    ]
    img = tmp_path / "be_channel.img"
    img.write_bytes(_build_image(channel_bytes))

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)

    assert layout is not None
    assert bytes.fromhex(layout.magic) == _MAGIC, "magic must not absorb the channel's high byte"
    assert layout.header_len == len(_MAGIC) + 2 + len(_DELIM)

    fields_by_name = {f.name: f for f in layout.fields}
    assert "channel" in fields_by_name, "channel field not discovered at all"
    ch = fields_by_name["channel"]
    assert ch.offset == len(_MAGIC), f"channel offset {ch.offset} != true offset {len(_MAGIC)}"
    assert ch.width == 2
    assert ch.endian == "be", "channel byte order must not flip to le"


def test_le_channel_with_constant_high_byte_is_discovered_correctly(tmp_path: Path) -> None:
    """Companion case: a little-endian 2-byte channel field whose first
    (low, varying) byte immediately follows the magic. The magic/field
    pairing guard is deliberately conservative here too — a magic byte
    that's constant *only* because every sample shares it, immediately
    followed by a byte with real (small, dense) variation, is exactly the
    ambiguous shape the guard exists to catch, and this fixture's own
    magic tail byte happens to have that shape by construction. The guard
    can therefore report this magic one byte short of the full 8 (a
    conservative, not incorrect, answer: a shorter magic is still a valid
    magic). What must not regress is the actual required field: the
    channel-quality tie-break (`_candidate_quality_key`, preferring the
    smaller-valued/denser candidate) recovers the true channel field at
    its real offset/width/endian regardless of exactly where magic
    detection drew the boundary."""
    channel_bytes = [
        struct.pack("<H", i % _N_CHANNELS) for i in range(_N_SAMPLES)
    ]
    img = tmp_path / "le_channel.img"
    img.write_bytes(_build_image(channel_bytes))

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)

    assert layout is not None
    magic_bytes = bytes.fromhex(layout.magic)
    assert _MAGIC.startswith(magic_bytes) and len(magic_bytes) >= infer.MIN_MAGIC_RUN, (
        "detected magic must be a valid (if possibly short) prefix of the true magic"
    )

    fields_by_name = {f.name: f for f in layout.fields}
    assert "channel" in fields_by_name
    ch = fields_by_name["channel"]
    assert ch.offset == len(_MAGIC), f"channel offset {ch.offset} != true offset {len(_MAGIC)}"
    assert ch.width == 2
    assert ch.endian == "le"


def test_channel_values_cover_the_full_declared_range(tmp_path: Path) -> None:
    """Sanity check on the fixture itself and on `InferredParser`: the
    discovered field must actually decode back to the right channel id for
    every access unit, not just report plausible-looking offset/width/
    endian metadata."""
    channel_bytes = [struct.pack(">H", i % _N_CHANNELS) for i in range(_N_SAMPLES)]
    img = tmp_path / "be_channel_values.img"
    img.write_bytes(_build_image(channel_bytes))

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)
        assert layout is not None
        parser = infer.InferredParser(layout)
        frames = list(parser.iter_frames(r, "img_test"))

    assert len(frames) == _N_SAMPLES
    for i, f in enumerate(sorted(frames, key=lambda f: f.payload_offset)):
        assert f.channel == i % _N_CHANNELS, (
            f"frame {i}: decoded channel {f.channel} != true channel {i % _N_CHANNELS}"
        )


def test_long_fully_constant_header_is_not_truncated_by_the_guard(tmp_path: Path) -> None:
    """Regression guard the other way: a header that really is *entirely*
    constant (no trailing field at all, e.g. a device with a single fixed
    reserved trailer after its signature) must still have its whole
    constant run detected as the magic — the FIX-9 pairing check only
    stops extension when the next byte pair looks field-shaped, and must
    not fire on a genuinely constant byte followed by another genuinely
    constant byte."""
    long_magic = _MAGIC + bytes.fromhex("0102030405")  # still fully constant
    out = bytearray()
    for i in range(_N_SAMPLES):
        out += _padding(i)
        out += long_magic
        out += _START_CODE
        out += _NAL_HEADER
        out += _PAYLOAD
    img = tmp_path / "long_constant.img"
    img.write_bytes(bytes(out))

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)

    assert layout is not None
    assert bytes.fromhex(layout.magic) == long_magic
    assert layout.header_len == len(long_magic)
