"""GENSIM (Tier C) writer — docs/01-FORENSIC-CORE.md §4.6 "GENSIM".

Raw Annex B H.264 access units from 2-3 channels with different
resolutions, interleaved in 256 KiB runs, no headers, no timestamps. Each
run belongs to exactly one channel and holds only whole access units (a run
ends once it reaches the target size, on an AU boundary — never mid-NAL),
so the file stays carvable by Annex-B start-code scanning; the "no
headers" instruction means there is nothing else on disk (no vendor frame
header, no index, no timestamps) — the ground truth still records each
access unit's synthetic timestamp, since scoring the carver needs a
reference even though the disk format itself carries none.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pramaan_synthdvr.scenario import SEIZURE_DEVICE_OFFSET_S, TRUE_EPOCH_S, iso, seed_for, us
from pramaan_synthdvr.truth import TruthBuilder, TruthFrame
from pramaan_synthdvr.video import (
    FRAME_INTERVAL_US,
    ChannelSpec,
    ClipSpec,
    au_bytes,
    is_keyframe_au,
    render_elementary_stream,
    split_clip_into_access_units,
)

RUN_SIZE = 256 * 1024
NUM_FRAMES = 100  # 8 s at 12.5 fps
RESOLUTIONS = [(640, 360), (704, 576), (1280, 720)]
CHANNEL_NAMES = ["Gate", "Shopfront", "Counter"]


@dataclass
class _ChannelStream:
    channel: ChannelSpec
    aus: list[list[tuple[int, bytes]]]
    device_start_s: float
    cursor: int = 0  # index into aus not yet placed into a run


def build_image(name: str, images_dir: Path, truth_dir: Path) -> Path:
    channels = [
        ChannelSpec(channel=i + 1, name=CHANNEL_NAMES[i], width=w, height=h)
        for i, (w, h) in enumerate(RESOLUTIONS)
    ]

    streams: list[_ChannelStream] = []
    for ch in channels:
        clip = ClipSpec(
            channel=ch,
            num_frames=NUM_FRAMES,
            start_epoch_s=TRUE_EPOCH_S,
            seed=seed_for(name, str(ch.channel)),
            motion_events=[],
        )
        stream = render_elementary_stream(clip)
        aus = split_clip_into_access_units(stream)
        streams.append(_ChannelStream(channel=ch, aus=aus, device_start_s=TRUE_EPOCH_S))

    truth = TruthBuilder(
        image=name,
        family="gensim",
        tier="C",
        device_model=None,
        device_serial=None,
        seizure_dvr_displayed="",
        seizure_reference="",
        channels=[{"channel": c.channel, "name": c.name} for c in channels],
        clock_segments=[
            {"start_device": iso(TRUE_EPOCH_S), "end_device": None, "offset_true_to_device_us": 0}
        ],
    )

    out = bytearray()
    byte_ranges: dict[int, list[list[int]]] = {c.channel: [] for c in channels}
    frame_seq: dict[int, int] = {c.channel: 0 for c in channels}

    remaining = list(streams)
    while remaining:
        still_remaining = []
        for s in remaining:
            run_start = len(out)
            run_bytes = 0
            while s.cursor < len(s.aus) and run_bytes < RUN_SIZE:
                au = s.aus[s.cursor]
                payload = au_bytes(au)
                offset = len(out)
                out.extend(payload)
                run_bytes += len(payload)

                i = frame_seq[s.channel.channel]
                ts_s = s.device_start_s + i * (FRAME_INTERVAL_US / 1_000_000)
                truth.add_frame(
                    TruthFrame(
                        channel=s.channel.channel,
                        ts_device_us=us(ts_s),
                        ts_true_us=us(ts_s),
                        ts_osd_us=us(ts_s),
                        header_offset=None,
                        payload_offset=offset,
                        payload_len=len(payload),
                        payload_sha256=hashlib.sha256(payload).hexdigest(),
                        frame_type="I" if is_keyframe_au(au) else "P",
                        recording_id=f"gensim-ch{s.channel.channel}",
                        deleted=False,
                        overwritten=False,
                    )
                )
                frame_seq[s.channel.channel] += 1
                s.cursor += 1
            if run_bytes:
                byte_ranges[s.channel.channel].append([run_start, run_bytes])
            if s.cursor < len(s.aus):
                still_remaining.append(s)
        remaining = still_remaining

    for s in streams:
        n = frame_seq[s.channel.channel]
        end_s = s.device_start_s + n * (FRAME_INTERVAL_US / 1_000_000)
        truth.recordings.append(
            {
                "channel": s.channel.channel,
                "start_device": iso(s.device_start_s),
                "end_device": iso(end_s),
                "frames": n,
                "byte_ranges": byte_ranges[s.channel.channel],
                "indexed": False,
                "deleted": False,
                "overwritten_frames": 0,
            }
        )

    seizure_true_s = TRUE_EPOCH_S + NUM_FRAMES * (FRAME_INTERVAL_US / 1_000_000) + 3600.0
    ist = timezone(timedelta(hours=5, minutes=30))
    ref_dt = datetime.fromtimestamp(seizure_true_s, tz=ist)
    truth.seizure_reference = ref_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    disp_dt = ref_dt + timedelta(seconds=SEIZURE_DEVICE_OFFSET_S)
    truth.seizure_dvr_displayed = disp_dt.strftime("%Y-%m-%dT%H:%M:%S")

    images_dir.mkdir(parents=True, exist_ok=True)
    out_path = images_dir / f"{name}.img"
    out_path.write_bytes(bytes(out))
    truth.write(truth_dir, out_path)
    return out_path
