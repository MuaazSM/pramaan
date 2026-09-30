"""Vendor-aware carvers (docs/01-FORENSIC-CORE.md §4.7 step 7): "DHAV
(header checksum + footer), HIKSIM-PS (pack/PES parsing + HKTS private
stream for absolute time)".

Both scan the given byte ranges for the vendor's own record-start
signature (:func:`pramaan_core.scan.scan_signatures`), then attempt a
structural, self-validating parse at each candidate offset — a genuine
DHAV/pack-header record validates its own checksum/footer/length fields, so
false positives from coincidental byte sequences inside compressed video
are rejected essentially for free. This recovers frames with no live index
at all (unlike the generic carver in ``pramaan_recovery.carve``, which has
no vendor header to lean on and so can't recover exact timestamps/channel
numbers), which is what makes it worth having a vendor-specific carver.
"""

from __future__ import annotations

import hashlib

from pramaan_core import scan
from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import ByteRange, FrameRef
from pramaan_formats import dhav, hwsim, mpegps, nalutil


def _consumed(consumed: list[tuple[int, int]], offset: int) -> bool:
    return any(s <= offset < e for s, e in consumed)


def carve_dhav(reader: EvidenceReader, image_id: str, ranges: list[ByteRange]) -> list[FrameRef]:
    """Recover DHAV frame records from ``ranges`` with no index at all
    (docs/01-FORENSIC-CORE.md §4.6 "DHSIM", §4.7 step 7)."""
    frames: list[FrameRef] = []
    for rng in ranges:
        start, end = rng.offset, rng.offset + rng.length
        if end <= start:
            continue
        data = reader.read(start, end - start)
        hits = scan.scan_signatures(reader.path, [b"DHAV"], start, end)
        candidate_offsets = sorted({offset for _, offset in hits})
        consumed: list[tuple[int, int]] = []
        for offset in candidate_offsets:
            if _consumed(consumed, offset):
                continue
            records = dhav.walk_dhav_stream(data, start, offset, end)
            if not records:
                continue
            consumed.append((offset, records[-1].end_offset))
            for record in records:
                local = record.payload_offset - start
                payload = data[local : local + record.payload_len]
                frame_type = record.frame_type if record.frame_type in ("I", "P") else "other"
                frame_id = hashlib.sha256(payload).hexdigest()[:24]
                frames.append(
                    FrameRef(
                        frame_id=frame_id,
                        image_id=image_id,
                        channel=record.channel,
                        stream="main",
                        codec="h264",
                        frame_type=frame_type,  # type: ignore[arg-type]
                        header_offset=record.header_offset,
                        payload_offset=record.payload_offset,
                        payload_len=record.payload_len,
                        ts_header_us=record.ts_us,
                        ts_index_us=None,
                        width=None,
                        height=None,
                        source="carved",
                        recording_id=None,
                        deleted=True,
                    )
                )
    frames.sort(key=lambda f: f.payload_offset)
    return frames


def carve_hwsim(reader: EvidenceReader, image_id: str, ranges: list[ByteRange]) -> list[FrameRef]:
    """Recover HWSIM 20-byte-headered NALs from ``ranges`` with no live
    channel-list entry at all (docs/01-FORENSIC-CORE.md §4.6 "HWSIM", §4.7
    step 7). Candidate offsets come from the fixed 3-byte marker every NAL
    header carries at bytes ``[1:4]`` (``hwsim.HW_HDR_FIXED``); structural
    validation (type byte, NAL length bounds, the start code right after
    the header) rejects coincidental matches almost for free, the same way
    ``carve_dhav``/``carve_hiksim_ps`` do for their own signatures.

    HWSIM's per-NAL header has no channel field (docs/01-FORENSIC-CORE.md
    §4.6) — unlike DHAV/HIKSIM-PS, a carved run alone can't say which
    channel it belongs to, and (this corpus's) HWSIM channels all share one
    resolution, so SPS-based clustering (``pramaan_recovery.carve``'s
    fallback) can't separate them either. The one channel-shaped hint left
    is the disk's own *layout* convention: every recording round writes one
    contiguous, sentinel-terminated run per live channel, in the same
    channel order every round (docs/progress/Q2.md's writer always iterates
    channels in ascending order). So each ``ByteRange`` is treated as one
    "round": runs found inside it are numbered by the order they're carved
    in and assigned channels by cycling through the *current* live channel
    roster (``hwsim.live_channel_roster``) in that same order. This is a
    documented, corpus-specific heuristic, not a general HWSIM guarantee —
    if the image has no readable channel list at all, channel is left
    ``None`` rather than guessed."""
    roster = hwsim.live_channel_roster(reader)
    frames: list[FrameRef] = []
    for rng in ranges:
        start, end = rng.offset, rng.offset + rng.length
        if end <= start:
            continue
        data = reader.read(start, end - start)
        hits = scan.scan_signatures(reader.path, [hwsim.HW_HDR_FIXED], start, end)
        candidate_offsets = sorted({offset - 1 for _, offset in hits if offset - 1 >= start})
        consumed: list[tuple[int, int]] = []
        run_index = 0
        for offset in candidate_offsets:
            if _consumed(consumed, offset):
                continue
            local = offset - start
            nals = hwsim.walk_hw_nals(data[local:], offset, end - offset)
            aus = hwsim.group_hw_access_units(nals)
            if not aus:
                continue
            last_nal = nals[-1]
            consumed.append((offset, last_nal.payload_offset + last_nal.nal_len))
            channel = roster[run_index % len(roster)] if roster else None
            run_index += 1
            for au in aus:
                frames.append(
                    hwsim.hw_au_to_frame_ref(
                        au,
                        image_id=image_id,
                        channel=channel,
                        stream="main",
                        recording_id=None,
                        source="carved",
                        deleted=True,
                    )
                )
    frames.sort(key=lambda f: f.payload_offset)
    return frames


def carve_hiksim_ps(
    reader: EvidenceReader, image_id: str, ranges: list[ByteRange]
) -> list[FrameRef]:
    """Recover HIKSIM MPEG-PS access units from ``ranges`` with no HIKBTREE
    entry at all (docs/01-FORENSIC-CORE.md §4.6 "HIKSIM", §4.7 step 7)."""
    frames: list[FrameRef] = []
    for rng in ranges:
        start, end = rng.offset, rng.offset + rng.length
        if end <= start:
            continue
        data = reader.read(start, end - start)
        hits = scan.scan_signatures(reader.path, [mpegps.PACK_START], start, end)
        candidate_offsets = sorted({offset for _, offset in hits})
        consumed: list[tuple[int, int]] = []
        for offset in candidate_offsets:
            if _consumed(consumed, offset):
                continue
            aus = mpegps.walk_ps_stream(data, start, offset, end)
            if not aus:
                continue
            consumed.append((offset, aus[-1].end_offset))
            for au in aus:
                local = au.payload_offset - start
                payload = data[local : local + au.payload_len]
                frame_type = nalutil.classify_access_unit(payload)
                frame_id = hashlib.sha256(payload).hexdigest()[:24]
                frames.append(
                    FrameRef(
                        frame_id=frame_id,
                        image_id=image_id,
                        channel=au.channel,
                        stream="main",
                        codec="h264",
                        frame_type=frame_type,  # type: ignore[arg-type]
                        header_offset=au.header_offset,
                        payload_offset=au.payload_offset,
                        payload_len=au.payload_len,
                        ts_header_us=au.ts_header_us,
                        ts_index_us=None,
                        width=None,
                        height=None,
                        source="carved",
                        recording_id=None,
                        deleted=True,
                    )
                )
    frames.sort(key=lambda f: f.payload_offset)
    return frames
