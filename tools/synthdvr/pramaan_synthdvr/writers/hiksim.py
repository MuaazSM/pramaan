"""HIKSIM (Hikvision-like, Tier A) writer.

Layout written exactly per docs/01-FORENSIC-CORE.md §4.6 "HIKSIM" (header,
HIKBTREE, IMKH + MPEG-PS data blocks with HKTS private PES, RATS logs).

Two documented spec byte-counts don't sum to the stated fixed record size
when every named field is laid out at its literal offset: the HIKBTREE
entry ("48 bytes each") sums to 44 bytes of named fields + "12 pad", and the
RATS log record ("64-byte records") sums to 60 bytes of named fields + "12
pad". Every named field here is written at exactly the offset implied by
the spec's field order; only the *trailing* padding field is enlarged (16
bytes instead of 12 in both cases) so the record hits its documented fixed
stride — parsers iterate by that fixed stride and never read the padding,
so this is a no-op for anyone reading the format, not a layout change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pramaan_synthdvr import pes
from pramaan_synthdvr.binutil import fixed_str, put, u8, u16, u32, u64
from pramaan_synthdvr.scenario import (
    DEFAULT_OSD_DRIFT_S,
    TRUE_EPOCH_S,
    default_channels,
    iso,
    seed_for,
    seizure_offset_us,
    us,
)
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

MAGIC = b"HIKVISION@HANGZHOU"
assert len(MAGIC) == 18

HEADER_PAGE = 0x1000
HIKBTREE_OFFSET = 0x1000
ENTRIES_START = 0x60
ENTRY_SIZE = 48
BLOCK_SIZE = 1 * 1024 * 1024  # scaled down from spec's 4 MiB "synthetic
# default" — docs/05-INFRA-QA.md §4.2 explicitly allows scaling region
# sizes down for fast tests, as long as parsers read them from the header.
RECORDING_FRAMES = 150  # 12 s at 12.5 fps, GOP 25 -> 6 GOPs
FORMAT_RECORDING_FRAMES = 60  # shorter, so the post-format write only
# partially overwrites the block it reuses (leaves recoverable tail bytes).
RECORDINGS_PER_CHANNEL = 2
LOG_AREA_CAPACITY = 32
LOG_RECORD_SIZE = 64
IMKH_HEADER_SIZE = 40

MODEL = "DVR-SIM-HIK-8CH"
SERIAL = "SIMHIK000123"

MINOR = {
    "power_on": 0x50,
    "login": 0x01,
    "logout": 0x02,
    "playback": 0x10,
    "export": 0x11,
    "hdd_format": 0x40,
    "time_change": 0x41,
}


def _round_up(n: int, unit: int) -> int:
    return ((n + unit - 1) // unit) * unit


@dataclass
class _Recording:
    channel: ChannelSpec
    rec_index: int
    generation: int
    device_start_s: float
    device_offset_s: float
    osd_start_s: float
    num_frames: int
    motion: list[MotionEvent]
    block_index: int
    id: str = field(default="")

    def __post_init__(self) -> None:
        self.id = hashlib.sha256(
            f"{self.channel.channel}|{self.generation}|{self.rec_index}|{self.block_index}".encode()
        ).hexdigest()[:16]

    @property
    def device_end_s(self) -> float:
        return self.device_start_s + self.num_frames * (FRAME_INTERVAL_US / 1_000_000)


def build_image(
    name: str,
    images_dir: Path,
    truth_dir: Path,
    *,
    scenario: str,
) -> Path:
    """scenario: "clean" | "format" | "clockchange"."""
    channels = default_channels()
    osd_drift = DEFAULT_OSD_DRIFT_S if scenario == "clockchange" else {}

    time_change_device_offset_s = -3600.0  # "clock set back 1 h at 02:00 device"
    time_change_boundary_rec_index = 1  # offset changes starting from rec_index 1

    def device_offset_for(rec_index: int) -> float:
        if scenario == "clockchange" and rec_index >= time_change_boundary_rec_index:
            return time_change_device_offset_s
        return 0.0

    gen1: list[_Recording] = []
    for rec_index in range(RECORDINGS_PER_CHANNEL):
        for ch in channels:
            offset_s = device_offset_for(rec_index)
            true_start_s = TRUE_EPOCH_S + rec_index * RECORDING_FRAMES * (
                FRAME_INTERVAL_US / 1_000_000
            )
            device_start_s = true_start_s + offset_s
            drift = osd_drift.get(ch.channel, 0.0)
            motion = [MotionEvent(40, 90)] if (ch.channel == 3 and rec_index == 0) else []
            gen1.append(
                _Recording(
                    channel=ch,
                    rec_index=rec_index,
                    generation=1,
                    device_start_s=device_start_s,
                    device_offset_s=offset_s,
                    osd_start_s=device_start_s + drift,
                    num_frames=RECORDING_FRAMES,
                    motion=motion,
                    block_index=len(gen1),
                )
            )

    block_count = len(gen1)

    gen2: list[_Recording] = []
    format_true_s = gen1[-1].device_end_s + 300.0  # 5 min after last gen1 recording
    if scenario == "format":
        for ch in channels:
            drift = osd_drift.get(ch.channel, 0.0)
            device_start_s = format_true_s + 60.0  # DVR resumes recording shortly after
            gen2.append(
                _Recording(
                    channel=ch,
                    rec_index=0,
                    generation=2,
                    device_start_s=device_start_s,
                    device_offset_s=0.0,
                    osd_start_s=device_start_s + drift,
                    num_frames=FORMAT_RECORDING_FRAMES,
                    motion=[],
                    block_index=ch.channel - 1,
                )
            )

    # --- layout ---
    hikbtree_size = _round_up(ENTRIES_START + block_count * ENTRY_SIZE, 0x1000)
    data_offset = _round_up(HIKBTREE_OFFSET + hikbtree_size, 0x1000)
    log_area_size = _round_up(LOG_AREA_CAPACITY * LOG_RECORD_SIZE, 0x1000)
    log_offset = data_offset + block_count * BLOCK_SIZE
    total_size = log_offset + log_area_size

    img = bytearray(total_size)

    truth = TruthBuilder(
        image=name,
        family="hiksim",
        tier="A",
        device_model=MODEL,
        device_serial=SERIAL,
        seizure_dvr_displayed="",
        seizure_reference="",
        channels=[{"channel": c.channel, "name": c.name} for c in channels],
    )

    def render_and_write_recording(rec: _Recording) -> int:
        """Render + encode ``rec``, write it into its block, add truth frames.
        Returns the number of bytes written after the IMKH header (i.e. the
        MPEG-PS stream length)."""
        clip = ClipSpec(
            channel=rec.channel,
            num_frames=rec.num_frames,
            start_epoch_s=rec.osd_start_s,
            seed=seed_for(name, str(rec.channel.channel), str(rec.generation), str(rec.rec_index)),
            motion_events=rec.motion,
        )
        stream = render_elementary_stream(clip)
        aus = split_clip_into_access_units(stream)

        block_abs = data_offset + rec.block_index * BLOCK_SIZE
        put(img, block_abs, b"IMKH" + u16(0x0100))  # + 34 zero pad (bytearray default)

        cursor = IMKH_HEADER_SIZE
        for i, au in enumerate(aus):
            device_ts_s = rec.device_start_s + i * (FRAME_INTERVAL_US / 1_000_000)
            true_ts_s = device_ts_s - rec.device_offset_s
            osd_ts_s = rec.osd_start_s + i * (FRAME_INTERVAL_US / 1_000_000)
            pts90 = round(device_ts_s * 90_000) & 0x1FFFFFFFF

            header_local = cursor
            pack = pes.pack_header(pts90)
            put(img, block_abs + cursor, pack)
            cursor += len(pack)

            if is_keyframe_au(au):
                unix_s = int(device_ts_s)
                ms = int(round((device_ts_s - unix_s) * 1000))
                priv = pes.private_pes(pes.hkts_payload(unix_s, ms, rec.channel.channel))
                put(img, block_abs + cursor, priv)
                cursor += len(priv)

            payload = au_bytes(au)
            packet = pes.video_pes(payload, pts90)
            prefix_len = len(packet) - len(payload)
            put(img, block_abs + cursor, packet)
            payload_offset = block_abs + cursor + prefix_len
            cursor += len(packet)

            truth.add_frame(
                TruthFrame(
                    channel=rec.channel.channel,
                    ts_device_us=us(device_ts_s),
                    ts_true_us=us(true_ts_s),
                    ts_osd_us=us(osd_ts_s),
                    header_offset=block_abs + header_local,
                    payload_offset=payload_offset,
                    payload_len=len(payload),
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                    frame_type="I" if is_keyframe_au(au) else "P",
                    recording_id=rec.id,
                    deleted=False,  # filled in below once generations are known
                    overwritten=False,
                )
            )
        if rec.motion:
            truth.motion_events.append(
                {
                    "channel": rec.channel.channel,
                    "start_true": iso(
                        rec.device_start_s
                        - rec.device_offset_s
                        + rec.motion[0].start_frame * (FRAME_INTERVAL_US / 1_000_000)
                    ),
                    "end_true": iso(
                        rec.device_start_s
                        - rec.device_offset_s
                        + rec.motion[0].end_frame * (FRAME_INTERVAL_US / 1_000_000)
                    ),
                }
            )
        return cursor  # header + PS stream length

    gen1_extent: dict[int, int] = {}
    for rec in gen1:
        gen1_extent[rec.block_index] = render_and_write_recording(rec)

    log_events: list[dict[str, Any]] = []
    power_on_s = gen1[0].device_start_s - 120.0
    login_s = gen1[0].device_start_s - 60.0
    log_events.append(
        {
            "ts": int(power_on_s),
            "major": 1,
            "minor": MINOR["power_on"],
            "user": "system",
            "channel": 0,
            "param1": 0,
            "param2": 0,
        }
    )
    log_events.append(
        {
            "ts": int(login_s),
            "major": 1,
            "minor": MINOR["login"],
            "user": "admin",
            "channel": 0,
            "param1": 0,
            "param2": 0,
        }
    )

    gen2_extent: dict[int, int] = {}
    if scenario == "format":
        format_login_s = format_true_s - 30.0
        log_events.append(
            {
                "ts": int(format_login_s),
                "major": 1,
                "minor": MINOR["login"],
                "user": "admin",
                "channel": 0,
                "param1": 0,
                "param2": 0,
            }
        )
        log_events.append(
            {
                "ts": int(format_true_s),
                "major": 1,
                "minor": MINOR["hdd_format"],
                "user": "admin",
                "channel": 0,
                "param1": 0,
                "param2": 0,
            }
        )

        for rec in gen2:
            gen2_extent[rec.block_index] = render_and_write_recording(rec)

        playback_s = gen2[-1].device_end_s + 30.0
        export_s = playback_s + 30.0
        logout_s = export_s + 30.0
        log_events.append(
            {
                "ts": int(playback_s),
                "major": 1,
                "minor": MINOR["playback"],
                "user": "admin",
                "channel": gen2[0].channel.channel,
                "param1": int(gen2[0].device_start_s),
                "param2": int(gen2[0].device_end_s),
            }
        )
        log_events.append(
            {
                "ts": int(export_s),
                "major": 1,
                "minor": MINOR["export"],
                "user": "admin",
                "channel": gen2[0].channel.channel,
                "param1": int(gen2[0].device_start_s),
                "param2": int(gen2[0].device_end_s),
            }
        )
        log_events.append(
            {
                "ts": int(logout_s),
                "major": 1,
                "minor": MINOR["logout"],
                "user": "admin",
                "channel": 0,
                "param1": 0,
                "param2": 0,
            }
        )
    elif scenario == "clockchange":
        tc_rec = next(
            r
            for r in gen1
            if r.rec_index == time_change_boundary_rec_index and r.channel.channel == 1
        )
        old_ts = int(
            tc_rec.device_start_s - time_change_device_offset_s
        )  # what device clock would have read
        new_ts = int(tc_rec.device_start_s)
        tc_ts = new_ts
        log_events.append(
            {
                "ts": tc_ts,
                "major": 1,
                "minor": MINOR["time_change"],
                "user": "admin",
                "channel": 0,
                "param1": old_ts,
                "param2": new_ts,
            }
        )
        truth.time_changes.append(
            {
                "ts_device": iso(tc_ts),
                "old_ts_us": old_ts * 1_000_000,
                "new_ts_us": new_ts * 1_000_000,
            }
        )
        playback_s = gen1[-1].device_end_s + 30.0
        logout_s = playback_s + 30.0
        log_events.append(
            {
                "ts": int(playback_s),
                "major": 1,
                "minor": MINOR["playback"],
                "user": "admin",
                "channel": 1,
                "param1": int(gen1[0].device_start_s),
                "param2": int(gen1[0].device_end_s),
            }
        )
        log_events.append(
            {
                "ts": int(logout_s),
                "major": 1,
                "minor": MINOR["logout"],
                "user": "admin",
                "channel": 0,
                "param1": 0,
                "param2": 0,
            }
        )
    else:
        playback_s = gen1[-1].device_end_s + 30.0
        logout_s = playback_s + 30.0
        log_events.append(
            {
                "ts": int(playback_s),
                "major": 1,
                "minor": MINOR["playback"],
                "user": "admin",
                "channel": 1,
                "param1": int(gen1[0].device_start_s),
                "param2": int(gen1[0].device_end_s),
            }
        )
        log_events.append(
            {
                "ts": int(logout_s),
                "major": 1,
                "minor": MINOR["logout"],
                "user": "admin",
                "channel": 0,
                "param1": 0,
                "param2": 0,
            }
        )

    log_events.sort(key=lambda e: e["ts"])
    assert len(log_events) <= LOG_AREA_CAPACITY
    for i, ev in enumerate(log_events):
        off = log_offset + i * LOG_RECORD_SIZE
        rec_bytes = bytearray(LOG_RECORD_SIZE)
        put(rec_bytes, 0, b"RATS")
        put(rec_bytes, 4, u32(ev["ts"]))
        put(rec_bytes, 8, u16(ev["major"]))
        put(rec_bytes, 10, u16(ev["minor"]))
        put(rec_bytes, 12, fixed_str(ev["user"], 16))
        put(rec_bytes, 28, u32(ev["channel"]))
        put(rec_bytes, 32, u64(ev["param1"]))
        put(rec_bytes, 40, u64(ev["param2"]))
        put(img, off, bytes(rec_bytes))
        kind = {v: k for k, v in MINOR.items()}[ev["minor"]]
        truth.log_events.append(
            {
                "kind": kind,
                "ts_device": iso(ev["ts"]),
                "user": ev["user"],
                "offset": off,
            }
        )

    # --- HIKBTREE ---
    put(img, HIKBTREE_OFFSET, b"HIKBTREE")
    entry_count = block_count if scenario != "format" else len(gen2)
    put(img, HIKBTREE_OFFSET + 0x10, u32(entry_count))

    def write_entry(slot: int, rec: _Recording) -> None:
        off = HIKBTREE_OFFSET + ENTRIES_START + slot * ENTRY_SIZE
        e = bytearray(ENTRY_SIZE)
        put(e, 0, u64(0))  # state = in use
        put(e, 8, u8(rec.channel.channel))
        put(e, 9, u8(1))  # has_footage
        put(e, 16, u32(int(rec.device_start_s)))
        put(e, 20, u32(int(rec.device_end_s)))
        put(e, 24, u64(data_offset + rec.block_index * BLOCK_SIZE))
        put(img, off, bytes(e))

    for rec in gen1:
        write_entry(rec.block_index, rec)
    for rec in gen2:
        write_entry(rec.block_index, rec)  # overwrites the gen1 entry in that slot

    # --- header ---
    init_time = int(gen1[0].device_start_s - 86_400) if scenario != "format" else int(format_true_s)
    put(img, 0x210, MAGIC)
    put(img, 0x230, u64(total_size))
    put(img, 0x240, u64(HIKBTREE_OFFSET))
    put(img, 0x248, u64(hikbtree_size))
    put(img, 0x250, u64(data_offset))
    put(img, 0x258, u64(BLOCK_SIZE))
    put(img, 0x260, u32(block_count))
    put(img, 0x270, u64(log_offset))
    put(img, 0x278, u64(log_area_size))
    put(img, 0x280, u32(init_time))
    put(img, 0x300, fixed_str(MODEL, 32))
    put(img, 0x320, fixed_str(SERIAL, 48))

    # --- recordings / deletions truth, now that overwritten extents are known ---
    if scenario == "format":
        per_channel_deleted: dict[int, list[_Recording]] = {}
        for r in gen1:
            per_channel_deleted.setdefault(r.channel.channel, []).append(r)
        for ch_no, recs in per_channel_deleted.items():
            starts = [r.device_start_s for r in recs]
            ends = [r.device_end_s for r in recs]
            truth.deletions.append(
                {
                    "channel": ch_no,
                    "start_device": iso(min(starts)),
                    "end_device": iso(max(ends)),
                    "method": "format",
                    "action_device": iso(format_true_s),
                    "actor": "admin",
                }
            )

    for f in truth.frames:
        rec_map = {r.id: r for r in gen1 + gen2}
        rec = rec_map[f.recording_id]
        f.deleted = scenario == "format" and rec.generation == 1
        if scenario == "format" and rec.generation == 1 and rec.block_index in gen2_extent:
            block_abs = data_offset + rec.block_index * BLOCK_SIZE
            overwritten_end = block_abs + gen2_extent[rec.block_index]
            f.overwritten = f.payload_offset < overwritten_end

    for rec in gen1 + gen2:
        frs = [f for f in truth.frames if f.recording_id == rec.id]
        truth.recordings.append(
            {
                "channel": rec.channel.channel,
                "start_device": iso(rec.device_start_s),
                "end_device": iso(rec.device_end_s),
                "frames": len(frs),
                "byte_ranges": [
                    [
                        data_offset + rec.block_index * BLOCK_SIZE,
                        (gen1_extent if rec.generation == 1 else gen2_extent)[rec.block_index],
                    ]
                ],
                "indexed": not (scenario == "format" and rec.generation == 1),
                "deleted": scenario == "format" and rec.generation == 1,
                "overwritten_frames": sum(1 for f in frs if f.overwritten),
            }
        )

    if scenario == "clockchange":
        boundary_ts = next(
            r.device_start_s for r in gen1 if r.rec_index == time_change_boundary_rec_index
        )
        truth.clock_segments = [
            {
                "start_device": iso(gen1[0].device_start_s),
                "end_device": iso(boundary_ts),
                "offset_true_to_device_us": 0,
            },
            {
                "start_device": iso(boundary_ts),
                "end_device": None,
                "offset_true_to_device_us": int(time_change_device_offset_s * 1_000_000),
            },
        ]
        truth.osd_drift_s = {str(k): v for k, v in DEFAULT_OSD_DRIFT_S.items()}
    else:
        truth.clock_segments = [
            {
                "start_device": iso(gen1[0].device_start_s),
                "end_device": None,
                "offset_true_to_device_us": 0,
            }
        ]

    # FIX-6: seizure displayed time = reference time + the device offset
    # actually baked into this image's last (open-ended) clock segment —
    # see pramaan_synthdvr.scenario.seizure_offset_us.
    seizure_true_s = (gen2[-1].device_end_s if gen2 else gen1[-1].device_end_s) + 3600.0
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
