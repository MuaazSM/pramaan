"""Format inference — the Tier B differentiator (docs/01-FORENSIC-CORE.md
§4.8).

``infer_layout(reader) -> InferredLayout | None`` is the B2 integration-
contract entry point (docs/progress/B2.md "Integration contract"). It knows
nothing about any *specific* vendor format — it discovers a small,
fixed-position per-frame header purely from where Annex B NAL start codes
land on disk, by treating the bytes immediately before every plausible NAL
as a table of samples and looking for columns (byte positions) that behave
like a magic, a channel id, a device timestamp, a length or a sequence
number. This module must never encode any XSIM-specific byte offset,
magic value, or field width (docs/01-FORENSIC-CORE.md §4.6's "blind
inference" rule; enforced by ``tests/validation/test_no_xsim_leak.py``).

Algorithm (docs/01-FORENSIC-CORE.md §4.8, numbered to match):

1. Sample up to 20,000 Annex B start codes with a plausible NAL type.
2. Take the 96 bytes before each one; align samples at the start code.
3. Magic: the earliest run of >= 3 low-entropy, near-constant byte
   positions -> candidate magic bytes; confirmed (and ``header_len`` set)
   by finding that exact byte string in each sample's own window and
   taking the modal distance back to the start code (>= 90% agreement
   required, else inference gives up and returns ``None``).
4. Fields: every (offset, width, endian) in the header is scored as a
   candidate for each role; the highest-scoring candidate wins each role,
   picked greedily, then removed from further consideration.
5. Overlaps are resolved by processing roles highest-score-first and
   skipping any candidate whose byte range already overlaps an accepted
   field.
6. ``emit_ksy``/``summarize_layout`` produce the draft ``.ksy`` and a
   human-readable summary for the UI.
7. :class:`InferredParser` replays the discovered layout to yield
   ``FrameRef``s with ``source="inferred"``.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pramaan_core import scan
from pramaan_core.evidence import EvidenceReader, hash_image
from pramaan_core.ids import content_id
from pramaan_core.models import FrameRef, InferredField, InferredLayout

#: docs/01-FORENSIC-CORE.md §4.8 step 1.
MAX_SAMPLES = 20_000
WINDOW = 96
MIN_MAGIC_RUN = 3
MAGIC_ENTROPY_MAX = 0.2
MAGIC_AGREEMENT_MIN = 0.90

_H264_PLAUSIBLE = frozenset({1, 5, 7, 8})
_H265_PLAUSIBLE = frozenset({1, 19, 20, 32, 33, 34})
_H264_IDR = 5
_H265_IDR_TYPES = frozenset({19, 20})

_WIDTHS = (2, 4, 8)
_ENDIANS: tuple[Literal["le", "be"], ...] = ("le", "be")
_STRUCT_CODE = {
    (2, "le"): "<H",
    (2, "be"): ">H",
    (4, "le"): "<I",
    (4, "be"): ">I",
    (8, "le"): "<Q",
    (8, "be"): ">Q",
}

LENGTH_MATCH_MIN = 0.95
TIMESTAMP_MONOTONIC_MIN = 0.98
SEQUENCE_STEP_MIN = 0.95
_YEAR_MIN = 2000
_YEAR_MAX = 2035
_FPS_MIN = 1.0
_FPS_MAX = 60.0
_UNITS: tuple[Literal["s", "ms", "us"], ...] = ("s", "ms", "us")
_UNIT_SCALE = {"s": 1, "ms": 1_000, "us": 1_000_000}


@dataclass(frozen=True)
class _Sample:
    start_code_offset: int
    nal_type: int
    codec: str
    is_idr: bool  # true if any NAL in this access unit is an IDR/keyframe NAL
    window: bytes  # exactly WINDOW bytes ending right before the start code


def _is_plausible(nal_type: int, codec: str) -> bool:
    if codec == "h264":
        return nal_type in _H264_PLAUSIBLE
    return nal_type in _H265_PLAUSIBLE


def _is_idr(nal_type: int, codec: str) -> bool:
    if codec == "h264":
        return nal_type == _H264_IDR
    return nal_type in _H265_IDR_TYPES


_H264_VCL = frozenset({1, 5})
_H265_VCL = frozenset({1, 19, 20})


def _is_vcl(nal_type: int, codec: str) -> bool:
    if codec == "h264":
        return nal_type in _H264_VCL
    return nal_type in _H265_VCL


def _access_unit_starts(
    hits: list[tuple[int, int, int, str]],
) -> list[tuple[int, int, str, bool]]:
    """Groups raw Annex B hits into access units — leading non-VCL NALs
    (SPS/PPS/...) attach to the following VCL (slice) NAL, the same
    convention every documented vendor format in this corpus uses to bundle
    one per-frame header ahead of a whole access unit
    (docs/01-FORENSIC-CORE.md §4.6/§4.7 step 2) — and returns each access
    unit's ``(first_offset, first_nal_type, codec, is_idr)``. Sampling only
    these "AU-initial" start codes is what makes step 2's "align samples at
    the start code" meaningful: a header only reliably precedes the first
    NAL of a bundle, not a later NAL bundled in behind it (e.g. a PPS's own
    trailing bytes precede that bundle's IDR slice, not the record
    header).

    Non-``_is_plausible`` hits are dropped *before* grouping, not merely
    excluded from the result: a custom per-frame header's own bytes can
    coincidentally contain a byte sequence the scanner misreads as an
    Annex B start code with an implausible NAL type (seen empirically:
    type 0/23 runs sitting exactly where a header's reserved/pad bytes
    would be) — left in, one of these would wrongly become "the" leading
    NAL of the *real* NAL that immediately follows it, silently absorbing
    and hiding a real access unit."""
    plausible_hits = [h for h in hits if _is_plausible(h[2], h[3])]
    starts: list[tuple[int, int, str, bool]] = []
    pending: tuple[int, int, str] | None = None
    pending_is_idr = False
    for offset, _sc_len, nal_type, codec in plausible_hits:
        if pending is None:
            pending = (offset, nal_type, codec)
            pending_is_idr = False
        if _is_idr(nal_type, codec):
            pending_is_idr = True
        if _is_vcl(nal_type, codec):
            starts.append((*pending, pending_is_idr))
            pending = None
    return starts


def _collect_samples(reader: EvidenceReader) -> list[_Sample]:
    hits = scan.scan_annexb(reader.path, 0, None, codec="auto")
    samples: list[_Sample] = []
    for offset, nal_type, codec, is_idr in _access_unit_starts(hits):
        if not _is_plausible(nal_type, codec):
            continue
        if offset < WINDOW:
            continue
        window = reader.read(offset - WINDOW, WINDOW)
        if len(window) != WINDOW:
            continue
        samples.append(
            _Sample(
                start_code_offset=offset,
                nal_type=nal_type,
                codec=codec,
                is_idr=is_idr,
                window=window,
            )
        )
        if len(samples) >= MAX_SAMPLES:
            break
    return samples


def _entropy_and_mode(values: list[int]) -> tuple[float, int]:
    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    total = len(values)
    entropy = 0.0
    for c in counts.values():
        p = c / total
        entropy -= p * math.log2(p)
    mode = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return entropy, mode


def _detect_magic(samples: list[_Sample]) -> tuple[bytes, int] | None:
    n = len(samples)
    if n == 0:
        return None
    per_pos_entropy: list[float] = []
    per_pos_mode: list[int] = []
    for pos in range(WINDOW):
        values = [s.window[pos] for s in samples]
        entropy, mode = _entropy_and_mode(values)
        per_pos_entropy.append(entropy)
        per_pos_mode.append(mode)

    run_start = None
    pos = 0
    while pos <= WINDOW - MIN_MAGIC_RUN:
        if all(per_pos_entropy[pos + k] < MAGIC_ENTROPY_MAX for k in range(MIN_MAGIC_RUN)):
            run_start = pos
            break
        pos += 1
    if run_start is None:
        return None

    run_end = run_start + MIN_MAGIC_RUN
    while run_end < WINDOW and per_pos_entropy[run_end] < MAGIC_ENTROPY_MAX:
        run_end += 1
    # Also try extending left, in case the minimal 3-run landed mid-magic.
    while run_start > 0 and per_pos_entropy[run_start - 1] < MAGIC_ENTROPY_MAX:
        run_start -= 1

    candidate_magic = bytes(per_pos_mode[run_start:run_end])

    distances: dict[int, int] = {}
    for s in samples:
        found = s.window.rfind(candidate_magic)
        if found == -1:
            continue
        distance = WINDOW - found
        distances[distance] = distances.get(distance, 0) + 1
    if not distances:
        return None
    best_distance, best_count = max(distances.items(), key=lambda kv: kv[1])
    if best_count / n < MAGIC_AGREEMENT_MIN:
        return None
    return candidate_magic, best_distance


def _extract_series(
    samples: list[_Sample], header_len: int, offset: int, width: int, endian: Literal["le", "be"]
) -> list[int] | None:
    if offset + width > header_len:
        return None
    code = _STRUCT_CODE[(width, endian)]
    out = []
    for s in samples:
        # `s.window` covers [start_code_offset - WINDOW, start_code_offset);
        # the header starts at `start_code_offset - header_len`, i.e. local
        # index `WINDOW - header_len` within the window.
        local = (WINDOW - header_len) + offset
        if local < 0 or local + width > WINDOW:
            return None
        out.append(struct.unpack(code, s.window[local : local + width])[0])
    return out


def _score_length(
    samples: list[_Sample], header_len: int, series: list[int]
) -> tuple[float, int]:
    matches = 0
    total = 0
    for i, s in enumerate(samples):
        if i + 1 < len(samples):
            actual = samples[i + 1].start_code_offset - header_len - s.start_code_offset
        else:
            continue  # can't know "payload end" generically; skip the last sample
        total += 1
        if actual == series[i]:
            matches += 1
    if total == 0:
        return 0.0, 0
    return matches / total, total


def _cardinality_ok(series: list[int]) -> bool:
    return 1 <= len(set(series)) <= 64


def _monotonic_fraction(values: list[int]) -> float:
    if len(values) < 2:
        return 1.0
    ok = sum(1 for a, b in zip(values, values[1:], strict=False) if b >= a)
    return ok / (len(values) - 1)


def _split_by_channel(series: list[int], channel: list[int] | None) -> list[list[int]]:
    if channel is None:
        return [series]
    groups: dict[int, list[int]] = {}
    for v, c in zip(series, channel, strict=True):
        groups.setdefault(c, []).append(v)
    return list(groups.values())


def _plausible_epoch(value: int, unit: Literal["s", "ms", "us"]) -> bool:
    try:
        seconds = value / _UNIT_SCALE[unit]
        dt = datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return False
    return _YEAR_MIN <= dt.year <= _YEAR_MAX


def _median(values: list[int]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _score_timestamp(
    series: list[int], channel: list[int] | None
) -> tuple[float, int, Literal["s", "ms", "us"]] | None:
    groups = _split_by_channel(series, channel)
    best: tuple[float, int, Literal["s", "ms", "us"]] | None = None
    for unit in _UNITS:
        if not all(_plausible_epoch(v, unit) for v in series[: min(len(series), 50)]):
            continue
        fractions = [_monotonic_fraction(g) for g in groups if len(g) >= 2]
        support = sum(max(0, len(g) - 1) for g in groups)
        if not fractions or support == 0:
            continue
        weighted = sum(_monotonic_fraction(g) * max(0, len(g) - 1) for g in groups) / support
        if weighted < TIMESTAMP_MONOTONIC_MIN:
            continue
        steps: list[int] = []
        for g in groups:
            steps.extend(b - a for a, b in zip(g, g[1:], strict=False) if b >= a)
        if not steps:
            continue
        median_step = _median(steps)
        if median_step <= 0:
            continue
        fps = _UNIT_SCALE[unit] / median_step
        if not (_FPS_MIN / 4 <= fps <= _FPS_MAX * 4):
            # generous slack around 1-60fps: sampling only plausible NAL
            # types (not every frame) can multiply the true per-frame step
            continue
        candidate = (weighted, support, unit)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best


def _score_sequence(series: list[int], channel: list[int] | None) -> tuple[float, int]:
    groups = _split_by_channel(series, channel)
    matches = 0
    total = 0
    for g in groups:
        for a, b in zip(g, g[1:], strict=False):
            total += 1
            if b - a == 1:
                matches += 1
    if total == 0:
        return 0.0, 0
    return matches / total, total


def _score_flags(series: list[int], idr_flags: list[bool]) -> tuple[float, int]:
    if len(set(series)) > 8:
        return 0.0, 0
    matches = 0
    for v, is_idr in zip(series, idr_flags, strict=True):
        bit = bool(v & 1)
        if bit == is_idr:
            matches += 1
    agree = matches / len(series)
    disagree = 1.0 - agree
    return max(agree, disagree), len(series)


@dataclass(frozen=True)
class _Candidate:
    offset: int
    width: int
    endian: Literal["le", "be"]
    series: list[int]


def _all_candidates(
    samples: list[_Sample], header_len: int, magic_range: tuple[int, int]
) -> list[_Candidate]:
    out = []
    for offset in range(header_len):
        for width in _WIDTHS:
            if offset + width > header_len:
                continue
            if offset < magic_range[1] and offset + width > magic_range[0]:
                continue  # overlaps the magic bytes themselves
            for endian in _ENDIANS:
                series = _extract_series(samples, header_len, offset, width, endian)
                if series is None:
                    continue
                out.append(_Candidate(offset=offset, width=width, endian=endian, series=series))
    return out


def infer_layout(reader: EvidenceReader) -> InferredLayout | None:
    samples = _collect_samples(reader)
    if len(samples) < 10:
        return None
    magic_result = _detect_magic(samples)
    if magic_result is None:
        return None
    magic_bytes, header_len = magic_result
    # Where the magic bytes sit inside the header (for candidate exclusion):
    # they were found ending at `header_len` back from the start code i.e.
    # at header-relative [header_len - distance_to_run_start ... ), but
    # `_detect_magic` only tracks distance to the *start* of the window
    # scan; recompute the magic's own header-relative span directly.
    magic_span = _magic_header_span(samples, header_len, magic_bytes)

    codec = samples[0].codec
    idr_flags = [s.is_idr for s in samples]

    candidates = _all_candidates(samples, header_len, magic_span)
    channel_candidates = [c for c in candidates if _cardinality_ok(c.series)]

    ts_best: tuple[_Candidate, float, int, Literal["s", "ms", "us"], list[int] | None] | None = None
    for ts_cand in candidates:
        for ch_cand in [None, *channel_candidates]:
            channel_series = ch_cand.series if ch_cand is not None else None
            scored = _score_timestamp(ts_cand.series, channel_series)
            if scored is None:
                continue
            weighted, support, unit = scored
            if ts_best is None:
                ts_best = (ts_cand, weighted, support, unit, channel_series)
            else:
                better = weighted > ts_best[1] or (
                    weighted == ts_best[1] and support > ts_best[2]
                )
                if better:
                    ts_best = (ts_cand, weighted, support, unit, channel_series)

    channel_best: tuple[_Candidate, float, int] | None = None
    if ts_best is not None and ts_best[4] is not None:
        chosen_channel_series = ts_best[4]
        for c in channel_candidates:
            if c.series == chosen_channel_series:
                # confidence: how much this channel improves timestamp
                # monotonicity vs. no split at all.
                unsplit = _score_timestamp(ts_best[0].series, None)
                unsplit_frac = unsplit[0] if unsplit is not None else 0.0
                improvement = max(0.0, ts_best[1] - unsplit_frac)
                confidence = min(0.99, 0.5 + improvement + 0.3)
                channel_best = (c, confidence, len(c.series))
                break
    if channel_best is None and channel_candidates:
        # No timestamp benefited from a channel split (e.g. a single-
        # channel device, or channels already interleave in strictly
        # increasing write-time order) — fall back to the lowest-offset
        # plausible channel-shaped candidate at a lower confidence.
        c = min(channel_candidates, key=lambda c: (c.offset, c.width))
        channel_best = (c, 0.5, len(c.series))

    fields: list[InferredField] = []
    used_ranges: list[tuple[int, int]] = [magic_span] if magic_span[1] > magic_span[0] else []

    def _overlaps(rng: tuple[int, int]) -> bool:
        return any(a < rng[1] and rng[0] < b for a, b in used_ranges)

    # Fixed priority order, not pure score: `channel`/`timestamp` were
    # already chosen by a joint search (they're not in competition with
    # each other), and both take precedence over `length`/`sequence`/
    # `flags` — `flags` in particular is not one of §4.8's required roles
    # and must never be allowed to steal bytes a required role also wants
    # (docs/01-FORENSIC-CORE.md §4.8's acceptance list is magic, channel,
    # timestamp, length, sequence — flags is a bonus).
    if channel_best is not None:
        rng = (channel_best[0].offset, channel_best[0].offset + channel_best[0].width)
        if not _overlaps(rng):
            used_ranges.append(rng)
            fields.append(
                InferredField(
                    name="channel",
                    offset=channel_best[0].offset,
                    width=channel_best[0].width,
                    endian=channel_best[0].endian,
                    unit="none",
                    confidence=channel_best[1],
                    support=channel_best[2],
                )
            )
    if ts_best is not None:
        rng = (ts_best[0].offset, ts_best[0].offset + ts_best[0].width)
        if not _overlaps(rng):
            used_ranges.append(rng)
            fields.append(
                InferredField(
                    name="timestamp",
                    offset=ts_best[0].offset,
                    width=ts_best[0].width,
                    endian=ts_best[0].endian,
                    unit=ts_best[3],
                    confidence=ts_best[1],
                    support=ts_best[2],
                )
            )

    length_best = max(
        (
            (c, *_score_length(samples, header_len, c.series))
            for c in candidates
            if not _overlaps((c.offset, c.offset + c.width))
        ),
        key=lambda t: (t[1], t[2]),
        default=None,
    )
    if length_best is not None and length_best[1] >= LENGTH_MATCH_MIN and length_best[2] > 0:
        rng = (length_best[0].offset, length_best[0].offset + length_best[0].width)
        used_ranges.append(rng)
        fields.append(
            InferredField(
                name="length",
                offset=length_best[0].offset,
                width=length_best[0].width,
                endian=length_best[0].endian,
                unit="none",
                confidence=length_best[1],
                support=length_best[2],
            )
        )

    channel_series_for_sequence = channel_best[0].series if channel_best is not None else None
    sequence_best = max(
        (
            (c, *_score_sequence(c.series, channel_series_for_sequence))
            for c in candidates
            if not _overlaps((c.offset, c.offset + c.width))
        ),
        key=lambda t: (t[1], t[2]),
        default=None,
    )
    if sequence_best is not None and sequence_best[1] >= SEQUENCE_STEP_MIN and sequence_best[2] > 0:
        rng = (sequence_best[0].offset, sequence_best[0].offset + sequence_best[0].width)
        used_ranges.append(rng)
        fields.append(
            InferredField(
                name="sequence",
                offset=sequence_best[0].offset,
                width=sequence_best[0].width,
                endian=sequence_best[0].endian,
                unit="none",
                confidence=sequence_best[1],
                support=sequence_best[2],
            )
        )

    flags_best = max(
        (
            (c, *_score_flags(c.series, idr_flags))
            for c in candidates
            if not _overlaps((c.offset, c.offset + c.width))
        ),
        key=lambda t: (t[1], t[2]),
        default=None,
    )
    if flags_best is not None and flags_best[1] > 0.9 and flags_best[2] > 0:
        rng = (flags_best[0].offset, flags_best[0].offset + flags_best[0].width)
        used_ranges.append(rng)
        fields.append(
            InferredField(
                name="flags",
                offset=flags_best[0].offset,
                width=flags_best[0].width,
                endian=flags_best[0].endian,
                unit="none",
                confidence=flags_best[1],
                support=flags_best[2],
            )
        )
    fields.sort(key=lambda f: f.offset)

    image_id = f"img_{hash_image(reader)[0][:16]}"
    layout_id = content_id(
        "layout",
        {
            "image_id": image_id,
            "header_len": header_len,
            "magic": magic_bytes.hex(),
            "fields": [f.model_dump() for f in fields],
        },
    )
    return InferredLayout(
        id=layout_id,
        image_id=image_id,
        header_len=header_len,
        magic=magic_bytes.hex(),
        fields=fields,
        codec=codec,  # type: ignore[arg-type]
        confirmed_by=None,
    )


def _magic_header_span(
    samples: list[_Sample], header_len: int, magic_bytes: bytes
) -> tuple[int, int]:
    """The magic bytes' own header-relative ``[start, end)`` span, found by
    searching for it within the first sample whose header fits fully in its
    96-byte window (falls back to ``(0, len(magic_bytes))`` if none do)."""
    for s in samples:
        local_header_start = WINDOW - header_len
        if local_header_start < 0:
            continue
        header_bytes = s.window[local_header_start:]
        found = header_bytes.find(magic_bytes)
        if found != -1:
            return found, found + len(magic_bytes)
    return 0, len(magic_bytes)


def summarize_layout(layout: InferredLayout) -> str:
    """A human-readable summary for the UI (docs/01-FORENSIC-CORE.md §4.8
    step 6), e.g. "20-byte header, magic 58565231, channel u16 be @+4,
    timestamp u64 be us @+12, length u32 le @+8"."""
    parts = [f"{layout.header_len}-byte header"]
    if layout.magic:
        parts.append(f"magic {layout.magic}")
    for f in sorted(layout.fields, key=lambda f: f.offset):
        width_bits = f.width * 8
        piece = f"{f.name} u{width_bits} {f.endian} @+{f.offset}"
        if f.unit != "none":
            piece += f" {f.unit}"
        parts.append(piece)
    return ", ".join(parts)


def emit_ksy(layout: InferredLayout, out_dir: Path) -> Path:
    """Writes a draft Kaitai Struct spec for ``layout`` to
    ``<out_dir>/<layout.id>.ksy`` (docs/01-FORENSIC-CORE.md §4.8 step 6;
    per §4.5's fallback, this is a *draft* alongside the hand-written
    ``struct``-based :class:`InferredParser`, not compiler output)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "meta:",
        f"  id: inferred_{layout.id}",
        "  endian: le",
        "seq:",
        "  - id: header",
        "    size: " + str(layout.header_len),
        "    doc: |",
        "      Draft, machine-inferred layout (confidence per field below).",
    ]
    for f in sorted(layout.fields, key=lambda f: f.offset):
        type_codes = {
            (2, "le"): "u2",
            (2, "be"): "u2be",
            (4, "le"): "u4",
            (4, "be"): "u4be",
            (8, "le"): "u8",
            (8, "be"): "u8be",
        }
        type_code = type_codes[(f.width, f.endian)]
        lines.append(
            f"  # {f.name} @ offset {f.offset}, width {f.width}, endian {f.endian}, "
            f"unit={f.unit}, confidence={f.confidence:.2f}, support={f.support} ({type_code})"
        )
    if layout.magic:
        lines.append(f"  # magic: {layout.magic}")
    path = out_dir / f"{layout.id}.ksy"
    path.write_text("\n".join(lines) + "\n")
    return path


class InferredParser:
    """Replays a discovered :class:`InferredLayout` to yield ``FrameRef``s
    (docs/01-FORENSIC-CORE.md §4.8 step 7). Not a :class:`VendorParser` —
    it doesn't know about a live index, only "every place the header+NAL
    pattern repeats", so every frame it yields is ``source="inferred"``."""

    def __init__(self, layout: InferredLayout) -> None:
        self.layout = layout
        self._field_by_name: dict[str, InferredField] = {f.name: f for f in layout.fields}

    def _field_value(self, window_before_start_code: bytes, name: str) -> int | None:
        f = self._field_by_name.get(name)
        if f is None:
            return None
        local = (WINDOW - self.layout.header_len) + f.offset
        if local < 0 or local + f.width > len(window_before_start_code):
            return None
        code = _STRUCT_CODE[(f.width, f.endian)]
        return int(struct.unpack(code, window_before_start_code[local : local + f.width])[0])

    def iter_frames(self, reader: EvidenceReader, image_id: str) -> Iterator[FrameRef]:
        """One :class:`FrameRef` per access unit (docs/01-FORENSIC-CORE.md
        §4.8 step 7), payload spanning the *whole* access unit from its
        first NAL's start code to the next access unit's header start — the
        same "one header, one bundled AU" convention HIKSIM/DHSIM use
        (docs/progress/Q2.md: HWSIM's own per-NAL header is the documented
        exception, not the default)."""
        hits = scan.scan_annexb(reader.path, 0, None, codec=self.layout.codec)
        plausible = _H264_PLAUSIBLE if self.layout.codec == "h264" else _H265_PLAUSIBLE
        typed_hits = [(h[0], 0, h[2], h[3]) for h in hits]
        entries = [
            (offset, nal_type, is_idr)
            for offset, nal_type, _codec, is_idr in _access_unit_starts(typed_hits)
            if nal_type in plausible
        ]
        for i, (offset, _nal_type, is_idr) in enumerate(entries):
            if offset < WINDOW:
                continue
            window = reader.read(offset - WINDOW, WINDOW)
            if len(window) != WINDOW:
                continue
            channel_val = self._field_value(window, "channel")
            ts_field = self._field_by_name.get("timestamp")
            ts_us: int | None = None
            if ts_field is not None:
                raw_ts = self._field_value(window, "timestamp")
                if raw_ts is not None:
                    ts_us = raw_ts * (1_000_000 // _UNIT_SCALE.get(ts_field.unit, 1_000_000))
            if i + 1 < len(entries):
                end = entries[i + 1][0] - self.layout.header_len
            else:
                end = reader.size
            payload_len = max(0, end - offset)
            payload = reader.read(offset, payload_len)
            frame_id = hashlib.sha256(payload).hexdigest()[:24]
            yield FrameRef(
                frame_id=frame_id,
                image_id=image_id,
                channel=channel_val,
                stream="main",
                codec=self.layout.codec,
                frame_type="I" if is_idr else "P",
                header_offset=offset - self.layout.header_len,
                payload_offset=offset,
                payload_len=payload_len,
                ts_header_us=ts_us,
                ts_index_us=None,
                width=None,
                height=None,
                source="inferred",
                recording_id=None,
                deleted=False,
            )
