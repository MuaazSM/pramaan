"""FIX-13 regression tests for blind-inference field-width underestimation
(docs/01-FORENSIC-CORE.md §4.8): when a numeric field's value never
exceeded a narrower range across every *sampled* record, its unused
high-order bytes are constant zero and FIX-9's "prefer the narrower/denser
candidate" tie-break picks the narrow reading, leaving the zero bytes as
unexplained header padding instead of recognising them as the same
field's own high-order half.

``infer.py``'s ``_extend_candidate_if_zero_padded`` widens such a field
back out (2->4, 4->8) when the extra bytes are (a) constant zero across
every sample, (b) not claimed by another field, and (c) the wider offset
is naturally aligned to the header start or the magic's end — the same
shape a real device's own wider, aligned counter would have, just never
observed using its full range in this corpus. Values never change, so
recall is unaffected; only the reported width/offset (and, slightly, the
field's confidence) do.

These use small, hand-built synthetic layouts of our own devising (never
XSIM's), matching ``tests/core/test_infer_channel_boundary.py``'s
approach — fast, corpus-independent, and outside
``tests/validation/test_no_xsim_leak.py``'s concern (which this file does
not touch)."""

from __future__ import annotations

import struct
from pathlib import Path

from pramaan_core.evidence import EvidenceReader
from pramaan_recovery import infer

_START_CODE = b"\x00\x00\x01"


def _nal_header(i: int) -> bytes:
    """Alternates IDR (type 5) and P-slice (type 1) headers — both
    H.264-plausible — so ``is_idr`` actually varies across samples. An
    "every frame is IDR" fixture makes any constant byte trivially
    "correlate" with the (constant) keyframe flag, which would otherwise
    let a spurious ``flags`` field win a byte range this module doesn't
    care about but would still clutter the discovered layout."""
    return bytes([0x65]) if i % 4 == 0 else bytes([0x41])


def _high_entropy_padding(seed: int, length: int) -> bytes:
    """``length`` bytes that vary a lot across samples (``seed`` = sample
    index) and are never zero, so they can never be mistaken for a
    low-entropy magic run or a zero-padded field, and can never
    accidentally form a start-code byte sequence."""
    raw = bytearray(range(seed, seed + length))
    for i, b in enumerate(raw):
        raw[i] = ((b * 131 + seed * 7) % 255) + 1
    return bytes(raw)


# --- Scenario 1: a 4-byte BE length that never needed its top 2 bytes ------
#
# Layout: magic(8) + channel(4, be) + guard(2) + timestamp(8, be, epoch s)
# + guard(2) + length(4, be) + delim(1). The 2-byte constant guards
# isolate channel/timestamp/length from each other so the low-cardinality
# fields (channel: 4 values; length's own top bytes: always 0) can never
# be paired, by FIX-9's magic-extension guard, with an unrelated
# low-cardinality neighbour that would make the guard mis-fire — that's a
# separate, already-documented ambiguity (docs/progress/FIX-9.md "Known
# gaps") this file isn't re-litigating. Channel and timestamp exist only
# so the real (channel, timestamp) pair wins the joint search outright and
# the channel-fallback path (which would otherwise be tempted by the
# length field's own always-zero top bytes — cardinality 1, maximal
# density — being mistaken for a single-valued "channel") never runs.

_MAGIC1 = bytes.fromhex("a17c4e902f6b88d1")
_N_SAMPLES1 = 64
_N_CHANNELS1 = 4
_CHANNEL_WIDTH1 = 4
_GUARD1 = bytes([0xFF, 0xFE])
_TS_WIDTH1 = 8
_LENGTH_WIDTH1 = 4
_DELIM1 = bytes([0xFA])
_HEADER_LEN1 = (
    len(_MAGIC1)
    + _CHANNEL_WIDTH1
    + len(_GUARD1)
    + _TS_WIDTH1
    + len(_GUARD1)
    + _LENGTH_WIDTH1
    + len(_DELIM1)
)
_PADDING_LEN1 = 96 - _HEADER_LEN1
_LENGTH_OFFSET1 = len(_MAGIC1) + _CHANNEL_WIDTH1 + len(_GUARD1) + _TS_WIDTH1 + len(_GUARD1)
_BASE_S1 = 1_700_000_000
_STEP_S1 = 4


def _build_narrow_be_length_image(*, little_endian_length: bool) -> tuple[bytes, list[int]]:
    """One access unit per sample; the length field's true value is always
    < 256 (well under 16 bits, let alone the field's own 32 bits), so its
    top 2 bytes are constant zero across every sample — the exact shape
    the validation feedback described. Returns the image bytes and the
    true length value encoded for each sample (payload bytes + the fixed
    "distance to next header" the scorer measures against)."""
    out = bytearray()
    lengths: list[int] = []
    for i in range(_N_SAMPLES1):
        channel = i % _N_CHANNELS1
        rnd = i // _N_CHANNELS1
        ts_s = _BASE_S1 + rnd * _STEP_S1 - channel
        payload_len = 40 + ((i * 3) % 140)
        # `_score_length` measures the byte distance from this sample's
        # start code to the next sample's magic start: start-code(3) +
        # nal-header(1) + this payload + next record's padding.
        length_val = len(_START_CODE) + 1 + payload_len + _PADDING_LEN1
        assert length_val < 256, "fixture bug: length must stay under 256"
        lengths.append(length_val)
        out += _high_entropy_padding(i, _PADDING_LEN1)
        out += _MAGIC1
        out += struct.pack(">I", channel)
        out += _GUARD1
        out += struct.pack(">Q", ts_s)
        out += _GUARD1
        out += struct.pack("<I" if little_endian_length else ">I", length_val)
        out += _DELIM1
        out += _START_CODE
        out += _nal_header(i)
        out += bytes([0xEE]) * payload_len
    return bytes(out), lengths


def test_be_4byte_length_under_65536_is_reported_at_full_width(tmp_path: Path) -> None:
    """The scenario the validation feedback described directly: a real
    4-byte big-endian length field whose values never exceed 256 (well
    under 65536) across the sample. Inference must report the field at
    its true width 4 (not the narrower, zero-padded 2-byte reading that
    also technically matches every value), at its true offset, and must
    still decode every sample's value correctly."""
    img_bytes, lengths = _build_narrow_be_length_image(little_endian_length=False)
    img = tmp_path / "be_length.img"
    img.write_bytes(img_bytes)

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)

    assert layout is not None
    assert layout.header_len == _HEADER_LEN1

    fields_by_name = {f.name: f for f in layout.fields}
    assert "length" in fields_by_name, "length field not discovered at all"
    length = fields_by_name["length"]
    assert length.offset == _LENGTH_OFFSET1, (
        f"length offset {length.offset} != true full-width offset {_LENGTH_OFFSET1}"
    )
    assert length.width == 4, f"length reported at width {length.width}, expected the full width 4"
    assert length.endian == "be"
    # Confidence is lowered (not disqualified) because the width decision
    # rests on zero padding alone: still meets docs/01-FORENSIC-CORE.md
    # §4.8's >= 0.9 acceptance floor, but strictly below a clean 1.0 match.
    assert 0.9 <= length.confidence < 1.0

    # Values are unchanged by the width extension: decode every sample's
    # length field at the reported offset/width/endian and check it
    # against what was actually encoded.
    with EvidenceReader.open(str(img)) as r:
        samples = infer._collect_samples(r)
    decoded = infer._extract_series(
        samples, layout.header_len, length.offset, length.width, length.endian
    )
    assert decoded is not None
    assert decoded == lengths, "decoded length values must match what the fixture encoded"


def test_le_4byte_length_under_65536_is_reported_at_full_width(tmp_path: Path) -> None:
    """Little-endian mirror of the scenario above: the field's low-order
    half comes first, so the true high-order (always-zero) half sits
    *after* it — inference must widen forward, not backward, to recover
    it, without disturbing the low-order bytes' own values."""
    img_bytes, lengths = _build_narrow_be_length_image(little_endian_length=True)
    img = tmp_path / "le_length.img"
    img.write_bytes(img_bytes)

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)

    assert layout is not None
    assert layout.header_len == _HEADER_LEN1

    fields_by_name = {f.name: f for f in layout.fields}
    assert "length" in fields_by_name
    length = fields_by_name["length"]
    assert length.offset == _LENGTH_OFFSET1
    assert length.width == 4
    assert length.endian == "le"
    assert 0.9 <= length.confidence < 1.0

    with EvidenceReader.open(str(img)) as r:
        samples = infer._collect_samples(r)
    decoded = infer._extract_series(
        samples, layout.header_len, length.offset, length.width, length.endian
    )
    assert decoded is not None
    assert decoded == lengths


# --- Scenario 2: a genuine narrow field must not swallow its neighbour ----
#
# Layout: magic(8) + filler(2, high-cardinality decoy, not a required
# role) + sequence(2, be, increments by 1) + length(2, be) + delim(1).
# Both sequence and length are *genuinely* 2 bytes wide — sequence's
# values are never zero-padded (they vary continuously), so widening
# length backward into sequence's bytes must be refused: the padding
# bytes it would absorb are real, varying data, not unclaimed zero
# padding.

_MAGIC2 = bytes.fromhex("a17c4e902f6b88d1")
_N_SAMPLES2 = 80
_SEQ_BASE2 = 1000
_DELIM2 = bytes([0xFB])
_HEADER_LEN2 = len(_MAGIC2) + 2 + 2 + 2 + len(_DELIM2)
_PADDING_LEN2 = 96 - _HEADER_LEN2
_SEQUENCE_OFFSET2 = len(_MAGIC2) + 2
_LENGTH_OFFSET2 = _SEQUENCE_OFFSET2 + 2


def _filler2(i: int) -> bytes:
    """A 2-byte decoy with real, high-cardinality variation (never a
    zero-padded shape) — purely to give magic detection an unambiguous,
    high-entropy byte immediately after the true 8-byte magic, so this
    fixture doesn't also exercise the separate, already-documented
    magic/low-cardinality-neighbour boundary ambiguity
    (docs/progress/FIX-9.md "Known gaps") that scenario 1 above avoids the
    same way with its guard bytes."""
    return bytes([((i * 131 + 7) % 251) + 1, ((i * 197 + 53) % 251) + 1])


def test_length_stays_narrow_next_to_a_real_sequence_field(tmp_path: Path) -> None:
    """A real 2-byte sequence field immediately precedes a real 2-byte
    length field (both big-endian). Widening length backward would only
    be justified if those 2 bytes were unclaimed, constant-zero padding —
    they're real, continuously-varying sequence data, so length must stay
    at width 2, and sequence must be discovered correctly alongside it."""
    out = bytearray()
    for i in range(_N_SAMPLES2):
        payload_len = 40 + i  # strictly increasing -> length cardinality
        # exceeds the channel role's 1-64 range, so it can't be mistaken
        # for a (degenerate, single-valued) channel by the no-timestamp
        # channel fallback before the length role gets a turn.
        length_val = len(_START_CODE) + 1 + payload_len + _PADDING_LEN2
        assert length_val < 65536
        out += _high_entropy_padding(i, _PADDING_LEN2)
        out += _MAGIC2
        out += _filler2(i)
        out += struct.pack(">H", _SEQ_BASE2 + i)
        out += struct.pack(">H", length_val)
        out += _DELIM2
        out += _START_CODE
        out += _nal_header(i)
        out += bytes([0xEE]) * payload_len
    img = tmp_path / "length_next_to_sequence.img"
    img.write_bytes(bytes(out))

    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)

    assert layout is not None
    assert bytes.fromhex(layout.magic) == _MAGIC2, "magic must be discovered at its true 8 bytes"
    assert layout.header_len == _HEADER_LEN2

    fields_by_name = {f.name: f for f in layout.fields}
    assert "sequence" in fields_by_name, "sequence field not discovered at all"
    assert "length" in fields_by_name, "length field not discovered at all"

    sequence = fields_by_name["sequence"]
    assert sequence.offset == _SEQUENCE_OFFSET2
    assert sequence.width == 2
    assert sequence.endian == "be"

    length = fields_by_name["length"]
    assert length.offset == _LENGTH_OFFSET2
    assert length.width == 2, (
        f"length was widened to {length.width} bytes, swallowing the real sequence field next to it"
    )
    assert length.endian == "be"
    # Not zero-padded, so no confidence penalty: a clean 0.95+ length match.
    assert length.confidence >= infer.LENGTH_MATCH_MIN

    # Fields must not overlap on disk.
    spans = sorted((f.offset, f.offset + f.width) for f in layout.fields)
    for (_a_start, a_end), (b_start, _b_end) in zip(spans, spans[1:], strict=False):
        assert a_end <= b_start, f"discovered fields overlap: {spans}"


def test_summary_and_ksy_record_the_zero_padding_rationale_when_asked(tmp_path: Path) -> None:
    """``summarize_layout``/``emit_ksy`` stay unchanged for existing callers
    (``extended_fields`` defaults to empty — see docstrings), but when a
    caller does know which field(s) the FIX-13 zero-padding rule widened
    (as ``infer_layout`` itself does, internally, while building
    ``length``/``sequence``/``timestamp``/``flags``), both the
    human-readable summary and the draft ``.ksy`` can carry that rationale
    for an examiner reviewing the draft layout."""
    img_bytes, _lengths = _build_narrow_be_length_image(little_endian_length=False)
    img = tmp_path / "be_length_summary.img"
    img.write_bytes(img_bytes)
    with EvidenceReader.open(str(img)) as r:
        layout = infer.infer_layout(r)
    assert layout is not None
    assert "length" in {f.name for f in layout.fields}

    plain_summary = infer.summarize_layout(layout)
    assert "length" in plain_summary
    assert "constant" not in plain_summary  # no rationale when not asked for

    annotated_summary = infer.summarize_layout(layout, extended_fields=frozenset({"length"}))
    assert "length" in annotated_summary
    assert infer._ZERO_PAD_RATIONALE in annotated_summary

    ksy_path = infer.emit_ksy(layout, tmp_path, extended_fields=frozenset({"length"}))
    ksy_text = ksy_path.read_text()
    assert "length" in ksy_text
    assert infer._ZERO_PAD_RATIONALE in ksy_text
