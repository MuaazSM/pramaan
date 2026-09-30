"""Generic Annex B carver (docs/01-FORENSIC-CORE.md §4.7 steps 1-5).

Works from raw NAL start-code hits (:func:`pramaan_core.scan.scan_annexb`)
alone — no vendor header, no index. This is the Tier C carver (GENSIM) and
the fallback for any family without a dedicated vendor carver.
``pramaan_recovery.vendor_carve``'s DHAV and HIKSIM-PS carvers supersede
this over their own byte ranges, because they can also recover exact
timestamps and channel numbers straight from the vendor's own per-frame
header — this carver has no such header to lean on, so timestamps are
``None`` and channel is inferred from SPS clustering (step 4 below).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pramaan_core import scan
from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import ByteRange, FrameRef

from pramaan_recovery.sps import MalformedSps, SpsInfo, parse_sps

NAL_NON_IDR = 1
NAL_IDR = 5
NAL_SEI = 6
NAL_SPS = 7
NAL_PPS = 8
VCL_TYPES = (NAL_IDR, NAL_NON_IDR)


@dataclass(frozen=True)
class _NalSpan:
    nal_type: int
    codec: str
    start_code_offset: int  # absolute offset of the NAL's start code
    payload_start: int  # absolute offset of the NAL's own bytes (after start code)
    payload_end: int  # absolute offset just past this NAL


@dataclass(frozen=True)
class CarvedAccessUnit:
    payload_offset: int  # absolute offset of the AU's first start code
    payload_len: int  # through the last NAL's end (start codes included)
    codec: str
    is_idr: bool
    sps: SpsInfo | None  # parsed SPS, if this AU carries one


def _nal_spans(hits: list[tuple[int, int, int, str]], range_end: int) -> list[_NalSpan]:
    spans = []
    for i, (offset, sc_len, nal_type, codec) in enumerate(hits):
        payload_end = hits[i + 1][0] if i + 1 < len(hits) else range_end
        spans.append(
            _NalSpan(
                nal_type=nal_type,
                codec=codec,
                start_code_offset=offset,
                payload_start=offset + sc_len,
                payload_end=payload_end,
            )
        )
    return spans


def group_access_units(spans: list[_NalSpan]) -> list[list[_NalSpan]]:
    """Group NAL spans into access units: leading non-VCL NALs (SPS/PPS/SEI)
    attach to the following VCL (slice) NAL — the same rule the synthetic
    corpus's own writer uses (docs/01-FORENSIC-CORE.md §4.7 step 2). A
    trailing run of non-VCL spans with no following VCL NAL (the carved
    range ends mid-AU) is dropped as incomplete."""
    aus: list[list[_NalSpan]] = []
    cur: list[_NalSpan] = []
    for span in spans:
        cur.append(span)
        if span.nal_type in VCL_TYPES:
            aus.append(cur)
            cur = []
    return aus


def _build_au(reader: EvidenceReader, spans: list[_NalSpan]) -> CarvedAccessUnit:
    first, last = spans[0], spans[-1]
    payload_offset = first.start_code_offset
    payload_len = last.payload_end - payload_offset
    sps: SpsInfo | None = None
    for span in spans:
        if span.nal_type == NAL_SPS and span.payload_end > span.payload_start:
            rbsp = reader.read(span.payload_start, span.payload_end - span.payload_start)
            try:
                sps = parse_sps(rbsp)
            except MalformedSps:
                sps = None
            break
    is_idr = any(s.nal_type == NAL_IDR for s in spans)
    return CarvedAccessUnit(
        payload_offset=payload_offset,
        payload_len=payload_len,
        codec=first.codec,
        is_idr=is_idr,
        sps=sps,
    )


def carve_access_units(
    reader: EvidenceReader, ranges: list[ByteRange], codec: str = "auto"
) -> list[CarvedAccessUnit]:
    """Step 1-3: scan ``ranges`` for Annex B NALs, group into access units,
    parse each AU's SPS (if it carries one)."""
    aus: list[CarvedAccessUnit] = []
    for rng in ranges:
        if rng.length <= 0:
            continue
        start, end = rng.offset, rng.offset + rng.length
        hits = scan.scan_annexb(reader.path, start, end, codec=codec)  # type: ignore[arg-type]
        spans = _nal_spans(hits, end)
        for group in group_access_units(spans):
            aus.append(_build_au(reader, group))
    aus.sort(key=lambda a: a.payload_offset)
    return aus


def _sps_key(sps: SpsInfo) -> tuple[int, int, int]:
    return (sps.width, sps.height, sps.profile_idc)


def assign_channels(aus: list[CarvedAccessUnit]) -> list[int]:
    """Step 4 (no vendor header): cluster AUs by SPS fingerprint (resolution
    + profile). ``aus`` must already be sorted by ``payload_offset``. An AU
    without its own SPS inherits the most recently seen cluster — correct
    for streams where channels are interleaved in contiguous runs (e.g.
    GENSIM's 256 KiB runs), not for a truly frame-interleaved stream."""
    cluster_id_by_key: dict[tuple[int, int, int], int] = {}
    channels: list[int] = []
    current: int | None = None
    for au in aus:
        if au.sps is not None:
            key = _sps_key(au.sps)
            if key not in cluster_id_by_key:
                cluster_id_by_key[key] = len(cluster_id_by_key) + 1
            current = cluster_id_by_key[key]
        channels.append(current if current is not None else 0)
    return channels


def to_frame_refs(
    reader: EvidenceReader,
    image_id: str,
    aus: list[CarvedAccessUnit],
    channels: list[int] | None = None,
) -> list[FrameRef]:
    """Step 5 (no vendor header): build ``FrameRef``s with
    ``ts_header_us=None`` (no timestamp to recover) and channel from
    :func:`assign_channels` unless the caller already knows better."""
    if channels is None:
        channels = assign_channels(aus)
    frames: list[FrameRef] = []
    for au, channel in zip(aus, channels, strict=True):
        payload = reader.read(au.payload_offset, au.payload_len)
        frame_id = hashlib.sha256(payload).hexdigest()[:24]
        frames.append(
            FrameRef(
                frame_id=frame_id,
                image_id=image_id,
                channel=channel if channel > 0 else None,
                stream="main",
                codec=au.codec,  # type: ignore[arg-type]
                frame_type="I" if au.is_idr else "P",
                header_offset=au.payload_offset,
                payload_offset=au.payload_offset,
                payload_len=au.payload_len,
                ts_header_us=None,
                ts_index_us=None,
                width=au.sps.width if au.sps else None,
                height=au.sps.height if au.sps else None,
                source="carved",
                recording_id=None,
                deleted=True,
            )
        )
    return frames


def carve_annexb(
    reader: EvidenceReader, image_id: str, ranges: list[ByteRange], codec: str = "auto"
) -> list[FrameRef]:
    """Full generic carve: scan, group, parse SPS, cluster channels, build
    ``FrameRef``s — one call for the common case."""
    aus = carve_access_units(reader, ranges, codec=codec)
    return to_frame_refs(reader, image_id, aus)
