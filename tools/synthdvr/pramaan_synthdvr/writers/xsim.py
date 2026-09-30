"""XSIM (undocumented vendor, Tier B) writer.

Layout written exactly per docs/05-INFRA-QA.md §4.6 "XSIM layout
(generator-only; CORE agents must not read this section)". That section is
this module's only spec — docs/01-FORENSIC-CORE.md §4.6 deliberately does
not document XSIM's on-disk layout at all, only the sector-0 fingerprint
string that CORE is allowed to use, and forbids CORE agents from reading
this file or the §4.6 XSIM section while implementing format inference
(docs/01-FORENSIC-CORE.md §4.8). `hidden_layout` in each image's truth JSON
records the real layout for scoring only; `tests/validation/test_no_xsim_leak.py`
fails the build if the frame magic ever appears under `packages/`.

Do not import anything from this module, and do not read this file, from
`packages/`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pramaan_synthdvr.binutil import crc32, put, u16_be, u32_be, u64_be
from pramaan_synthdvr.scenario import TRUE_EPOCH_S, iso, seed_for, seizure_offset_us, us
from pramaan_synthdvr.truth import TruthBuilder, TruthFrame
from pramaan_synthdvr.video import (
    FRAME_INTERVAL_US,
    ChannelSpec,
    ClipSpec,
    MotionEvent,
    au_bytes,
    is_keyframe_au,
    render_elementary_stream,
    split_clip_into_access_units,
)

SECTOR0_MAGIC = b"XVR-GENERIC-2026"
assert len(SECTOR0_MAGIC) == 16
DATA_START = 4096  # first 4 KiB reserved for sector 0's fingerprint + padding

FRAME_MAGIC = bytes.fromhex("5AA53CC3")
HEADER_LEN = 28
CHUNK_SIZE = 1024 * 1024  # 1 MiB
FLAG_KEYFRAME = 0x0001

DEFAULT_CHANNEL_NAMES = ["Gate", "Shopfront", "Counter", "Rear lane"]
RECORDING_FRAMES = 90  # ~7.2 s at 12.5 fps


def _xsim_frame_header(*, channel: int, flags: int, seq: int, ts_us: int, payload: bytes) -> bytes:
    h = bytearray(HEADER_LEN)
    put(h, 0, FRAME_MAGIC)
    put(h, 4, u16_be(channel))
    put(h, 6, u16_be(flags))
    put(h, 8, u32_be(seq))
    put(h, 12, u64_be(ts_us))
    put(h, 20, u32_be(len(payload)))
    put(h, 24, u32_be(crc32(payload)))
    return bytes(h)


def _append_frame(buf: bytearray, frame_bytes: bytes) -> int:
    """Append ``frame_bytes`` to ``buf``, honouring the "frames are packed
    in 1 MiB chunks... chunk tail zero-padded" rule: a frame is never split
    across a chunk boundary. Returns the absolute (buf-local) offset the
    frame was actually written at."""
    pos = len(buf)
    chunk_end = ((pos // CHUNK_SIZE) + 1) * CHUNK_SIZE
    if pos + len(frame_bytes) > chunk_end:
        buf.extend(b"\x00" * (chunk_end - pos))
        pos = len(buf)
    buf.extend(frame_bytes)
    return pos


@dataclass(frozen=True)
class _PlacedFrame:
    ts_s: float
    channel: ChannelSpec
    au: list[tuple[int, bytes]]


def _channel_aus(
    name: str,
    ch: ChannelSpec,
    round_index: int,
    start_s: float,
    num_frames: int,
    motion: list[MotionEvent],
) -> list[_PlacedFrame]:
    clip = ClipSpec(
        channel=ch,
        num_frames=num_frames,
        start_epoch_s=start_s,
        seed=seed_for(name, str(ch.channel), str(round_index)),
        motion_events=motion,
    )
    stream = render_elementary_stream(clip)
    aus = split_clip_into_access_units(stream)
    return [
        _PlacedFrame(ts_s=start_s + i * (FRAME_INTERVAL_US / 1_000_000), channel=ch, au=au)
        for i, au in enumerate(aus)
    ]


def _rec_id(round_index: int, channel: int) -> str:
    return hashlib.sha256(f"{channel}|{round_index}".encode()).hexdigest()[:16]


def _write_generation(
    *,
    name: str,
    channels: list[ChannelSpec],
    round_index: int,
    start_s: float,
    num_frames: int,
    motion_map: dict[int, list[MotionEvent]],
    buf: bytearray,
    truth: TruthBuilder,
) -> None:
    """Render one generation's worth of per-channel clips and interleave
    them into ``buf`` in recording (timestamp) order, across channels —
    docs/05-INFRA-QA.md §4.6: "Frames of different channels interleave in
    recording order." """
    placed: list[_PlacedFrame] = []
    for ch in channels:
        placed.extend(
            _channel_aus(name, ch, round_index, start_s, num_frames, motion_map.get(ch.channel, []))
        )
    placed.sort(key=lambda p: (p.ts_s, p.channel.channel))

    seq_counters: dict[int, int] = dict.fromkeys((c.channel for c in channels), 0)
    for p in placed:
        payload = au_bytes(p.au)
        seq = seq_counters[p.channel.channel]
        seq_counters[p.channel.channel] = seq + 1
        is_i = is_keyframe_au(p.au)
        ts_us = us(p.ts_s)
        header = _xsim_frame_header(
            channel=p.channel.channel,
            flags=FLAG_KEYFRAME if is_i else 0,
            seq=seq,
            ts_us=ts_us,
            payload=payload,
        )
        offset = _append_frame(buf, header + payload)
        truth.add_frame(
            TruthFrame(
                channel=p.channel.channel,
                ts_device_us=ts_us,
                ts_true_us=ts_us,
                ts_osd_us=ts_us,
                header_offset=offset,
                payload_offset=offset + HEADER_LEN,
                payload_len=len(payload),
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                frame_type="I" if is_i else "P",
                recording_id=_rec_id(round_index, p.channel.channel),
                deleted=False,
                overwritten=False,
            )
        )


def _hidden_layout() -> dict[str, Any]:
    return {
        "header_len": HEADER_LEN,
        "magic": FRAME_MAGIC.hex(),
        "fields": [
            {"name": "magic", "offset": 0, "width": 4, "endian": "be", "unit": None},
            {"name": "channel", "offset": 4, "width": 2, "endian": "be", "unit": None},
            {"name": "flags", "offset": 6, "width": 2, "endian": "be", "unit": None},
            {"name": "sequence", "offset": 8, "width": 4, "endian": "be", "unit": None},
            {"name": "timestamp", "offset": 12, "width": 8, "endian": "be", "unit": "us"},
            {"name": "length", "offset": 20, "width": 4, "endian": "be", "unit": None},
            {"name": "crc32", "offset": 24, "width": 4, "endian": "be", "unit": None},
        ],
    }


def _add_recording_truth(
    truth: TruthBuilder, *, channel: int, round_index: int, start_s: float, num_frames: int
) -> None:
    rid = _rec_id(round_index, channel)
    frs = sorted(
        (f for f in truth.frames if f.recording_id == rid),
        key=lambda f: f.header_offset or 0,
    )
    end_s = start_s + num_frames * (FRAME_INTERVAL_US / 1_000_000)
    # Channels interleave within a generation (docs/05-INFRA-QA.md §4.6), so
    # one recording's frames are *not* contiguous in the data area — record
    # one byte range per frame rather than a single misleading min..max span.
    byte_ranges = [
        [f.header_offset, (f.payload_offset + f.payload_len) - (f.header_offset or 0)] for f in frs
    ]
    truth.recordings.append(
        {
            "channel": channel,
            "start_device": iso(start_s),
            "end_device": iso(end_s),
            "frames": len(frs),
            "byte_ranges": byte_ranges,
            "indexed": False,  # docs/05-INFRA-QA.md §4.6: "No index."
            "deleted": frs[0].deleted if frs else False,
            "overwritten_frames": sum(1 for f in frs if f.overwritten),
        }
    )


def build_image(name: str, images_dir: Path, truth_dir: Path, *, scenario: str) -> Path:
    """scenario: "none" | "format"."""
    channels = [
        ChannelSpec(channel=i + 1, name=n, width=640, height=360)
        for i, n in enumerate(DEFAULT_CHANNEL_NAMES)
    ]
    motion_map = {3: [MotionEvent(15, 40)]}

    truth = TruthBuilder(
        image=name,
        family="xsim",
        tier="B",
        device_model=None,
        device_serial=None,
        seizure_dvr_displayed="",
        seizure_reference="",
        channels=[{"channel": c.channel, "name": c.name} for c in channels],
        clock_segments=[
            {"start_device": iso(TRUE_EPOCH_S), "end_device": None, "offset_true_to_device_us": 0}
        ],
        hidden_layout=_hidden_layout(),
    )

    round_gap_s = RECORDING_FRAMES * (FRAME_INTERVAL_US / 1_000_000) + 60.0

    if scenario == "none":
        round_starts = [TRUE_EPOCH_S, TRUE_EPOCH_S + round_gap_s]
        data_buf = bytearray()
        for r, start_s in enumerate(round_starts):
            _write_generation(
                name=name,
                channels=channels,
                round_index=r,
                start_s=start_s,
                num_frames=RECORDING_FRAMES,
                motion_map=motion_map if r == 0 else {},
                buf=data_buf,
                truth=truth,
            )
        for f in truth.frames:
            f.deleted = False

        for r, start_s in enumerate(round_starts):
            for ch in channels:
                _add_recording_truth(
                    truth,
                    channel=ch.channel,
                    round_index=r,
                    start_s=start_s,
                    num_frames=RECORDING_FRAMES,
                )
        seizure_anchor_end = round_starts[-1] + RECORDING_FRAMES * (FRAME_INTERVAL_US / 1_000_000)

    elif scenario == "format":
        gen1_starts = [TRUE_EPOCH_S, TRUE_EPOCH_S + round_gap_s]
        gen1_buf = bytearray()
        for r, start_s in enumerate(gen1_starts):
            _write_generation(
                name=name,
                channels=channels,
                round_index=r,
                start_s=start_s,
                num_frames=RECORDING_FRAMES,
                motion_map=motion_map if r == 0 else {},
                buf=gen1_buf,
                truth=truth,
            )
        gen1_len = len(gen1_buf)
        gen1_frame_count = len(truth.frames)

        format_true_s = gen1_starts[-1] + RECORDING_FRAMES * (FRAME_INTERVAL_US / 1_000_000) + 300.0
        gen2_start_s = format_true_s + 60.0
        gen2_round = 2  # a fresh recording session after "format"
        gen2_buf = bytearray()
        _write_generation(
            name=name,
            channels=channels,
            round_index=gen2_round,
            start_s=gen2_start_s,
            num_frames=RECORDING_FRAMES,
            motion_map={},
            buf=gen2_buf,
            truth=truth,
        )
        overwrite_len = len(gen2_buf)
        assert overwrite_len <= gen1_len, "gen2 write must fit within gen1's data region"

        data_buf = bytearray(gen1_buf)
        data_buf[0:overwrite_len] = gen2_buf

        for i, f in enumerate(truth.frames):
            if i < gen1_frame_count:
                f.deleted = True
                f.overwritten = (f.header_offset or 0) < overwrite_len
            else:
                f.deleted = False

        for r, start_s in enumerate(gen1_starts):
            for ch in channels:
                _add_recording_truth(
                    truth,
                    channel=ch.channel,
                    round_index=r,
                    start_s=start_s,
                    num_frames=RECORDING_FRAMES,
                )
        for ch in channels:
            _add_recording_truth(
                truth,
                channel=ch.channel,
                round_index=gen2_round,
                start_s=gen2_start_s,
                num_frames=RECORDING_FRAMES,
            )

        gen1_end_s = gen1_starts[-1] + RECORDING_FRAMES * (FRAME_INTERVAL_US / 1_000_000)
        # One merged per-channel finding spanning every gen1 round (matches
        # the DHSIM/HIKSIM/HWSIM "format" convention: a single format action
        # deletes every prior recording on that channel in one event).
        for ch in channels:
            truth.deletions.append(
                {
                    "channel": ch.channel,
                    "start_device": iso(gen1_starts[0]),
                    "end_device": iso(gen1_end_s),
                    "method": "format",
                    "action_device": iso(format_true_s),
                    "actor": None,  # XSIM has no documented log format
                }
            )
        seizure_anchor_end = gen2_start_s + RECORDING_FRAMES * (FRAME_INTERVAL_US / 1_000_000)
    else:
        raise ValueError(f"unknown xsim scenario {scenario!r}")

    # ---- assemble the image: sector 0 fingerprint + data area ----
    img = bytearray(DATA_START)
    put(img, 0, SECTOR0_MAGIC)
    img.extend(data_buf)

    # ---- fix up truth frame/recording offsets now that the absolute data base is known ----
    for f in truth.frames:
        f.payload_offset += DATA_START
        if f.header_offset is not None:
            f.header_offset += DATA_START
    for rec in truth.recordings:
        rec["byte_ranges"] = [[off + DATA_START, ln] for off, ln in rec["byte_ranges"]]

    seizure_true_s = seizure_anchor_end + 3600.0
    ist = timezone(timedelta(hours=5, minutes=30))
    ref_dt = datetime.fromtimestamp(seizure_true_s, tz=ist)
    truth.seizure_reference = ref_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    disp_dt = ref_dt + timedelta(microseconds=seizure_offset_us(truth.clock_segments))
    truth.seizure_dvr_displayed = disp_dt.strftime("%Y-%m-%dT%H:%M:%S")

    images_dir.mkdir(parents=True, exist_ok=True)
    out_path = images_dir / f"{name}.img"
    out_path.write_bytes(bytes(img))
    truth.write(truth_dir, out_path)
    return out_path
